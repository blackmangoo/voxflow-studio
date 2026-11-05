-- =============================================================================
-- VOXFLOW STUDIO — PER-USER WHATSAPP DELIVERY & VERIFICATION MIGRATION
-- Project Ref: ouqjlqqgnboytjvudylv (blackmangoo's Org)
-- Ensures each customer receives WhatsApp video completion alerts ONLY on their
-- own verified WhatsApp number/ID, never on the Founder Admin's personal phone.
-- =============================================================================

alter table public.profiles
    add column if not exists wa_agent_token text not null default '',
    add column if not exists wa_user_id text not null default '',
    add column if not exists wa_verified boolean not null default false;

-- Allow authenticated users to update their own profile fields (full_name, wa_agent_token, wa_user_id, wa_verified)
-- while strictly forbidding self-escalation of role, plan_tier, or credits_balance.
drop policy if exists "profiles_update_name_only" on public.profiles;
create policy "profiles_update_name_only" on public.profiles
    for update to authenticated
    using (auth.uid() = id)
    with check (
        auth.uid() = id
        and role = (select p.role from public.profiles p where p.id = auth.uid())
        and credits_balance = (select p.credits_balance from public.profiles p where p.id = auth.uid())
        and plan_tier = (select p.plan_tier from public.profiles p where p.id = auth.uid())
    );
