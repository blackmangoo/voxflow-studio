-- =============================================================================
-- VOXFLOW STUDIO — CANCELLED JOB STATUS, SERIES UPDATE RLS & CHECKOUT LEADS
-- Project Ref: ouqjlqqgnboytjvudylv (blackmangoo's Org)
-- =============================================================================

-- 1. Allow 'cancelled' in public.render_jobs status check constraint
alter table public.render_jobs
    drop constraint if exists render_jobs_status_check;

alter table public.render_jobs
    add constraint render_jobs_status_check
    check (status in ('queued', 'running', 'completed', 'failed', 'cancelled'));

-- 2. Allow authenticated users to update (pause/resume) their own saved series
drop policy if exists "series_update_own" on public.series;
create policy "series_update_own" on public.series
    for update to authenticated
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

-- 3. Create public.checkout_leads table for Hybrid Concierge Checkout (Option C)
create table if not exists public.checkout_leads (
    id text primary key,
    email text not null,
    whatsapp text not null default '',
    plan_tier text not null default 'both_daily',
    payment_method text not null default 'whatsapp_concierge',
    notes text not null default '',
    status text not null default 'pending' check (status in ('pending', 'contacted', 'provisioned', 'dismissed')),
    created_at timestamptz not null default now()
);

create index if not exists idx_checkout_leads_created_at on public.checkout_leads(created_at desc);

alter table public.checkout_leads enable row level security;

drop policy if exists "checkout_leads_insert_public" on public.checkout_leads;
create policy "checkout_leads_insert_public" on public.checkout_leads
    for insert to anon, authenticated
    with check (char_length(email) >= 5);

drop policy if exists "checkout_leads_admin_select" on public.checkout_leads;
create policy "checkout_leads_admin_select" on public.checkout_leads
    for select to authenticated
    using (
        exists (
            select 1 from public.profiles p
            where p.id = auth.uid() and p.role = 'admin'
        )
    );

drop policy if exists "checkout_leads_admin_delete" on public.checkout_leads;
create policy "checkout_leads_admin_delete" on public.checkout_leads
    for delete to authenticated
    using (
        exists (
            select 1 from public.profiles p
            where p.id = auth.uid() and p.role = 'admin'
        )
    );
