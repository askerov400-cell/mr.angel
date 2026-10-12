-- Server-only acquaintance scheduling. Existing memory is not changed.
create table public.acquaintance_profiles (
 telegram_user_id bigint primary key check (telegram_user_id > 0),
 enabled boolean not null default false,
 updated_at timestamptz not null default now()
);
create table public.acquaintance_questions (
 id uuid primary key default gen_random_uuid(),
 telegram_user_id bigint not null references public.acquaintance_profiles,
 local_day date not null,
 slot smallint not null check (slot between 0 and 29),
 scheduled_at timestamptz not null,
 status text not null default 'planned' check (status in ('planned','sending','sent','answered','skipped','expired')),
 question_text text check (length(question_text) between 1 and 400),
 question_hash text generated always as (md5(lower(btrim(question_text)))) stored,
 message_id bigint,
 prompt_message_id bigint,
 sent_at timestamptz,
 answer_text text check (length(answer_text) between 1 and 1400),
 updated_at timestamptz not null default now(),
 unique (telegram_user_id,local_day,slot),
 check ((scheduled_at at time zone 'Asia/Qyzylorda')::date=local_day),
 check ((scheduled_at at time zone 'Asia/Qyzylorda')::time >= time '09:00'
    and (scheduled_at at time zone 'Asia/Qyzylorda')::time < time '23:00')
);
create index acquaintance_due_idx on public.acquaintance_questions (telegram_user_id,status,scheduled_at);
create index acquaintance_open_idx on public.acquaintance_questions (telegram_user_id,scheduled_at) where status in ('sending','sent');
create unique index acquaintance_unique_question_idx on public.acquaintance_questions (telegram_user_id,question_hash) where question_text is not null;
alter table public.acquaintance_profiles enable row level security;
alter table public.acquaintance_questions enable row level security;
revoke all on public.acquaintance_profiles,public.acquaintance_questions from public,anon,authenticated;
grant select,insert,update,delete on public.acquaintance_profiles,public.acquaintance_questions to service_role;

create function public.acquaintance_action(p_owner bigint,p_action text,p_id uuid default null,p_data jsonb default '{}')
returns setof jsonb language plpgsql security invoker set search_path='' as $$
declare q public.acquaintance_questions; enabled_now boolean; item jsonb; text_value text; memory_value text; summary_value text; plan_size integer;
begin
 if p_owner <= 0 then raise exception 'Invalid owner'; end if;
 if p_action='enable' then
  insert into public.acquaintance_profiles (telegram_user_id,enabled) values (p_owner,true)
  on conflict (telegram_user_id) do update set enabled=true,updated_at=now();
 end if;
 select enabled into enabled_now from public.acquaintance_profiles where telegram_user_id=p_owner for update;
 if not found then return; end if;
 if p_action in ('enable','pause','status') then
  if p_action='pause' then
   update public.acquaintance_profiles set enabled=false,updated_at=now() where telegram_user_id=p_owner;
   enabled_now := false;
  end if;
  return next jsonb_build_object('telegram_user_id',p_owner,'enabled',enabled_now,
   'pending',(select to_jsonb(a) from public.acquaintance_questions a where telegram_user_id=p_owner and status in ('sending','sent') order by scheduled_at limit 1));
  return;
 elsif p_action='plan' then
  if not enabled_now then return; end if;
  if jsonb_typeof(p_data->'times') is distinct from 'array' then raise exception 'Invalid plan'; end if;
  plan_size := jsonb_array_length(p_data->'times');
  -- Ten slots remain accepted during rolling deployment of the old worker.
  if plan_size <> 10 and plan_size not between 20 and 30 then raise exception 'Invalid plan'; end if;
  if exists (select 1 from jsonb_array_elements(p_data->'times') with ordinality as t(value,n)
   where (value->>'slot')::integer is distinct from n-1) then raise exception 'Invalid slots'; end if;
  if exists (select 1 from (
   select (value->>'at')::timestamptz as at,
    lag((value->>'at')::timestamptz) over (order by n) as previous
   from jsonb_array_elements(p_data->'times') with ordinality as t(value,n)) a
   where at-previous < interval '10 minutes') then raise exception 'Invalid spacing'; end if;
  if not exists (select 1 from public.acquaintance_questions where telegram_user_id=p_owner and local_day=(p_data->>'day')::date) then
   for item in select value from jsonb_array_elements(p_data->'times') loop
    insert into public.acquaintance_questions (telegram_user_id,local_day,slot,scheduled_at)
     values (p_owner,(p_data->>'day')::date,(item->>'slot')::smallint,(item->>'at')::timestamptz);
   end loop;
  end if;
  return next jsonb_build_object('telegram_user_id',p_owner,'planned',true,'plan_version',2);return;
 elsif p_action in ('claim','test') then
  if not enabled_now then return; end if;
  if p_action='claim' and ( (now() at time zone 'Asia/Qyzylorda')::time < time '09:00'
    or (now() at time zone 'Asia/Qyzylorda')::time >= time '23:00') then return; end if;
  update public.acquaintance_questions set status='expired',updated_at=now()
   where telegram_user_id=p_owner and status='planned' and scheduled_at < now()-interval '15 minutes' and p_action='claim';
  if p_action='test' and exists (select 1 from public.acquaintance_questions
   where telegram_user_id=p_owner and status in ('sending','sent')) then return; end if;
  if exists (select 1 from public.acquaintance_questions where telegram_user_id=p_owner
   and (sent_at > now()-interval '10 minutes'
    or (status='sending' and updated_at > now()-interval '10 minutes'))) then return; end if;
  select * into q from public.acquaintance_questions where telegram_user_id=p_owner and status='planned'
   and ((p_action='claim' and scheduled_at <= now()) or (p_action='test' and local_day=(now() at time zone 'Asia/Qyzylorda')::date)) order by scheduled_at limit 1;
  if not found then return; end if;
  update public.acquaintance_questions set status='sending',updated_at=now() where id=q.id returning * into q;
  return next to_jsonb(q);return;
 elsif p_action='by_message' then
  return query select to_jsonb(a) from public.acquaintance_questions a where telegram_user_id=p_owner
   and (message_id=(p_data->>'message_id')::bigint or prompt_message_id=(p_data->>'message_id')::bigint) limit 1;return;
 elsif p_action='history' then
  return query select to_jsonb(a) from (select question_text,answer_text,telegram_user_id from public.acquaintance_questions
   where telegram_user_id=p_owner and question_text is not null order by scheduled_at desc limit 100) a;return;
 end if;
 select * into q from public.acquaintance_questions where id=p_id and telegram_user_id=p_owner for update;
 if not found then return; end if;
 if p_action='get' then return next to_jsonb(q);return; end if;
 if p_action='answer' and q.status='answered' then return next jsonb_build_object('telegram_user_id',p_owner,'saved',true,'already',true);return; end if;
 if q.status not in ('sending','sent') then return; end if;
 if p_action='prepare' then
  if not enabled_now or (not coalesce((p_data->>'manual')::boolean,false)
   and ((now() at time zone 'Asia/Qyzylorda')::time < time '09:00'
    or (now() at time zone 'Asia/Qyzylorda')::time >= time '23:00')) then
   update public.acquaintance_questions set status='skipped',updated_at=now() where id=q.id;return;
  end if;
  text_value:=btrim(p_data->>'text');
  if text_value is null or length(text_value) not between 1 and 400 then raise exception 'Invalid question'; end if;
  if exists (select 1 from public.acquaintance_questions where telegram_user_id=p_owner and id<>q.id and question_hash=md5(lower(text_value))) then
   update public.acquaintance_questions set status='skipped',updated_at=now() where id=q.id;return;
  end if;
  update public.acquaintance_questions set question_text=text_value,updated_at=now() where id=q.id returning * into q;
 elsif p_action='sent' then
  if (p_data->>'message_id')::bigint <= 0 then raise exception 'Invalid message'; end if;
  update public.acquaintance_questions set status='sent',sent_at=now(),message_id=(p_data->>'message_id')::bigint,updated_at=now() where id=q.id returning * into q;
 elsif p_action='prompt' then
  if (p_data->>'message_id')::bigint <= 0 then raise exception 'Invalid message'; end if;
  update public.acquaintance_questions set prompt_message_id=(p_data->>'message_id')::bigint,updated_at=now() where id=q.id returning * into q;
 elsif p_action='skip' then
  update public.acquaintance_questions set status='skipped',updated_at=now() where id=q.id returning * into q;
 elsif p_action='answer' then
  text_value:=btrim(p_data->>'text');
  if q.question_text is null or text_value is null or length(text_value) not between 1 and 1400 then raise exception 'Invalid answer'; end if;
  summary_value := btrim(coalesce(p_data->>'memory_text',text_value));
  if summary_value is null or length(summary_value) not between 1 and 1600 then raise exception 'Invalid summary'; end if;
  memory_value:='Вопрос Хранителя: '||q.question_text||E'\nОтвет владельца: '||summary_value;
  insert into public.memory_entries (telegram_user_id,memory_type,category,memory_text,confidence)
   values (p_owner,'FACT','acquaintance_answer',memory_value,1.0)
   on conflict (telegram_user_id,memory_type,text_hash) do nothing;
  update public.acquaintance_questions set status='answered',answer_text=text_value,updated_at=now() where id=q.id;
  return next jsonb_build_object('telegram_user_id',p_owner,'saved',true,'already',false);return;
 else raise exception 'Invalid action'; end if;
 return next to_jsonb(q);
end;
$$;
revoke all on function public.acquaintance_action(bigint,text,uuid,jsonb) from public,anon,authenticated;
grant execute on function public.acquaintance_action(bigint,text,uuid,jsonb) to service_role;
notify pgrst,'reload schema';
