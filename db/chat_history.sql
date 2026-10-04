begin;
create table public.chat_messages (
    id bigint generated always as identity primary key,
    telegram_user_id bigint not null check (telegram_user_id > 0),
    chat_id bigint not null check (chat_id = telegram_user_id),
    telegram_message_id bigint not null check (telegram_message_id > 0),
    role text not null check (role in ('user','assistant')),
    content text not null,
    created_at timestamptz not null default now(),
    unique (chat_id, telegram_message_id)
);
create index chat_messages_owner_recent_idx on public.chat_messages (telegram_user_id,id desc);
alter table public.chat_messages enable row level security;
revoke all on public.chat_messages from public,anon,authenticated;
revoke all on sequence public.chat_messages_id_seq from public,anon,authenticated;
grant select,insert on public.chat_messages to service_role;
grant usage,select on sequence public.chat_messages_id_seq to service_role;
commit;
