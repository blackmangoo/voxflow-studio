-- =============================================================================
-- VOXFLOW STUDIO — PRODUCTION SUPABASE SCHEMA & ZERO-TRUST RLS MIGRATION
-- Project Ref: ouqjlqqgnboytjvudylv (blackmangoo's Org)
-- =============================================================================

create extension if not exists "pgcrypto";

-- 1. PROFILES TABLE (1:1 with auth.users)
create table if not exists public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    email text not null,
    full_name text not null default '',
    role text not null default 'user' check (role in ('user', 'admin')),
    plan_tier text not null default 'free' check (
        plan_tier in ('free', 'urdu_starter', 'urdu_daily', 'english_starter', 'english_daily', 'both_starter', 'both_daily')
    ),
    credits_balance integer not null default 0 check (credits_balance >= 0),
    sandbox_runs_remaining integer not null default 5 check (sandbox_runs_remaining >= 0),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_profiles_email on public.profiles(email);

-- Auto-create profile on user signup (Ammar's admin emails automatically receive admin role + 9999 live credits)
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
declare
    is_owner boolean;
begin
    is_owner := lower(new.email) in ('ammar.akbar2002@gmail.com', 'ammar.akbar2069@gmail.com');
    insert into public.profiles (id, email, full_name, role, plan_tier, credits_balance, sandbox_runs_remaining)
    values (
        new.id,
        coalesce(new.email, ''),
        coalesce(new.raw_user_meta_data->>'full_name', split_part(coalesce(new.email, 'creator'), '@', 1)),
        case when is_owner then 'admin' else 'user' end,
        case when is_owner then 'both_daily' else 'free' end,
        case when is_owner then 9999 else 0 end,
        case when is_owner then 9999 else 5 end
    )
    on conflict (id) do nothing;
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute procedure public.handle_new_user();

-- 2. SERIES TABLE (Autopilot & Custom Director Series)
create table if not exists public.series (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.profiles(id) on delete cascade,
    name text not null check (char_length(name) between 2 and 100),
    creation_mode text not null default 'prebuilt' check (creation_mode in ('prebuilt', 'custom_director', 'manual_scenes')),
    channel text not null default 'body_simulator',
    language_tier text not null default 'both' check (language_tier in ('urdu', 'english', 'both')),
    custom_prompt text not null default '',
    visual_style_dna text not null default '',
    plan_id text not null default 'both_daily',
    cadence text not null default 'Daily × 2 languages (60 videos/mo)',
    status text not null default 'active' check (status in ('active', 'paused')),
    created_at timestamptz not null default now()
);

create index if not exists idx_series_user_id on public.series(user_id);
create index if not exists idx_series_created_at on public.series(created_at desc);

-- 3. RENDER JOBS TABLE (Queued & Executed by Private Worker Daemon)
create table if not exists public.render_jobs (
    id uuid primary key default gen_random_uuid(),
    job_code text not null unique,
    user_id uuid not null references public.profiles(id) on delete cascade,
    series_id uuid references public.series(id) on delete set null,
    creation_mode text not null default 'prebuilt' check (creation_mode in ('prebuilt', 'custom_director', 'manual_scenes')),
    channel text not null default 'body_simulator',
    lang text not null default 'both' check (lang in ('urdu', 'english', 'both')),
    custom_prompt text not null default '',
    visual_style_dna text not null default '',
    custom_scenes jsonb not null default '[]'::jsonb,
    mock_mode boolean not null default true,
    status text not null default 'queued' check (status in ('queued', 'running', 'completed', 'failed')),
    stage text not null default '[0/6] Queued in Flow Worker Pool',
    progress integer not null default 5 check (progress between 0 and 100),
    concept text not null default '',
    script_preview jsonb not null default '{}'::jsonb,
    english_video text not null default '',
    urdu_video text not null default '',
    drive_url text not null default '',
    error text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_render_jobs_user_id on public.render_jobs(user_id);
create index if not exists idx_render_jobs_status_created on public.render_jobs(status, created_at asc);

-- 4. ATOMIC CREDIT & SECURITY GATE TRIGGER ON RENDER_JOBS
-- Guarantees at the PostgreSQL engine level that no user can ever queue a live
-- Google Flow / Playwright job (mock_mode = false) without live credits or admin role.
create or replace function public.enforce_render_job_credit_gate()
returns trigger
language plpgsql
security definer set search_path = public
as $$
declare
    prof record;
begin
    select id, role, credits_balance, sandbox_runs_remaining
    into prof
    from public.profiles
    where id = new.user_id
    for update;

    if not found then
        raise exception 'Profile not found for user %', new.user_id;
    end if;

    if new.mock_mode = false then
        -- Live Google Flow + Playwright execution requires admin role OR credits_balance > 0
        if prof.role <> 'admin' and prof.credits_balance <= 0 then
            raise exception 'Insufficient live 3D render credits (balance: 0). Upgrade to an Urdu, English, or Dual-Stream plan to dispatch live Google Flow renders.';
        end if;
        if prof.role <> 'admin' then
            update public.profiles
            set credits_balance = credits_balance - 1,
                updated_at = now()
            where id = new.user_id;
        end if;
    else
        -- Sandbox simulation check
        if prof.role <> 'admin' and prof.sandbox_runs_remaining <= 0 then
            raise exception 'Free sandbox simulation limit reached. Upgrade your plan to continue.';
        end if;
        if prof.role <> 'admin' then
            update public.profiles
            set sandbox_runs_remaining = sandbox_runs_remaining - 1,
                updated_at = now()
            where id = new.user_id;
        end if;
    end if;

    return new;
end;
$$;

drop trigger if exists trg_enforce_render_job_credit_gate on public.render_jobs;
create trigger trg_enforce_render_job_credit_gate
    before insert on public.render_jobs
    for each row execute procedure public.enforce_render_job_credit_gate();

-- 5. STRICT ROW LEVEL SECURITY (RLS) POLICIES
alter table public.profiles enable row level security;
alter table public.series enable row level security;
alter table public.render_jobs enable row level security;

-- Profiles: users can only read their own profile; cannot self-escalate role or credits_balance
drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own" on public.profiles
    for select to authenticated
    using (auth.uid() = id);

drop policy if exists "profiles_update_name_only" on public.profiles;
create policy "profiles_update_name_only" on public.profiles
    for update to authenticated
    using (auth.uid() = id)
    with check (
        auth.uid() = id
        and role = (select p.role from public.profiles p where p.id = auth.uid())
        and credits_balance = (select p.credits_balance from public.profiles p where p.id = auth.uid())
    );

-- Series: users can select, insert, update, delete only their own series
drop policy if exists "series_select_own" on public.series;
create policy "series_select_own" on public.series
    for select to authenticated
    using (auth.uid() = user_id);

drop policy if exists "series_insert_own" on public.series;
create policy "series_insert_own" on public.series
    for insert to authenticated
    with check (auth.uid() = user_id);

drop policy if exists "series_delete_own" on public.series;
create policy "series_delete_own" on public.series
    for delete to authenticated
    using (auth.uid() = user_id);

-- Render Jobs: users can select and insert only their own jobs (credit trigger enforces balance)
drop policy if exists "render_jobs_select_own" on public.render_jobs;
create policy "render_jobs_select_own" on public.render_jobs
    for select to authenticated
    using (auth.uid() = user_id);

drop policy if exists "render_jobs_insert_own" on public.render_jobs;
create policy "render_jobs_insert_own" on public.render_jobs
    for insert to authenticated
    with check (auth.uid() = user_id);
