begin;

create table public.memory_entries (
    id bigint generated always as identity primary key,
    telegram_user_id bigint not null check (telegram_user_id > 0),
    memory_type text not null check (memory_type in ('FACT','GOAL','EVENT','OBSERVATION')),
    category text not null,
    memory_text text not null check (length(trim(memory_text)) between 1 and 2000),
    text_hash text generated always as (md5(lower(btrim(memory_text)))) stored,
    confidence double precision not null check (confidence between 0.8 and 1),
    created_at timestamptz not null default now(),
    unique (telegram_user_id, memory_type, text_hash)
);
create index memory_entries_user_recent_idx on public.memory_entries (telegram_user_id, id desc);

create table public.user_states (
    telegram_user_id bigint not null check (telegram_user_id > 0),
    state_key text not null check (state_key ~ '^[a-z][a-z0-9_]{0,63}$'),
    state_value jsonb not null check (jsonb_typeof(state_value) in ('string','number','boolean')),
    category text not null,
    unit text,
    confidence double precision not null check (confidence between 0.8 and 1),
    updated_at timestamptz not null default now(),
    primary key (telegram_user_id, state_key)
);
create index user_states_recent_idx on public.user_states (telegram_user_id, updated_at desc);

create table public.state_history (
    id bigint generated always as identity primary key,
    telegram_user_id bigint not null,
    state_key text not null,
    state_value jsonb not null,
    unit text,
    recorded_at timestamptz not null,
    replaced_at timestamptz not null default now(),
    foreign key (telegram_user_id, state_key) references public.user_states (telegram_user_id, state_key)
);
create index state_history_user_key_idx on public.state_history (telegram_user_id, state_key, id);

create function public.record_state_history() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin
    insert into public.state_history (telegram_user_id,state_key,state_value,unit,recorded_at)
    values (old.telegram_user_id,old.state_key,old.state_value,old.unit,old.updated_at);
    return new;
end;
$$;
create trigger state_changed before update on public.user_states
for each row when (old.state_value is distinct from new.state_value or old.unit is distinct from new.unit)
execute function public.record_state_history();

create function public.save_user_state(
    p_user_id bigint, p_key text, p_value jsonb, p_category text, p_unit text, p_confidence double precision
) returns table (saved boolean)
language plpgsql security invoker set search_path = '' as $$
begin
    insert into public.user_states as s (telegram_user_id,state_key,state_value,category,unit,confidence)
    values (p_user_id,p_key,p_value,p_category,p_unit,p_confidence)
    on conflict (telegram_user_id,state_key) do update
    set state_value=excluded.state_value, category=excluded.category, unit=excluded.unit,
        confidence=excluded.confidence, updated_at=now()
    where s.state_value is distinct from excluded.state_value or s.unit is distinct from excluded.unit;
    return query select found;
end;
$$;

alter table public.memory_entries enable row level security;
alter table public.user_states enable row level security;
alter table public.state_history enable row level security;
revoke all on public.memory_entries, public.user_states, public.state_history from public, anon, authenticated;
revoke all on sequence public.memory_entries_id_seq, public.state_history_id_seq from public, anon, authenticated;
grant select,insert on public.memory_entries, public.state_history to service_role;
grant select,insert,update on public.user_states to service_role;
grant usage,select on sequence public.memory_entries_id_seq, public.state_history_id_seq to service_role;
revoke all on function public.record_state_history() from public, anon, authenticated;
revoke all on function public.save_user_state(bigint,text,jsonb,text,text,double precision) from public, anon, authenticated;
grant execute on function public.save_user_state(bigint,text,jsonb,text,text,double precision) to service_role;

commit;
