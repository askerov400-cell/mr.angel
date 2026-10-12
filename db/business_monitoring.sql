begin;
create table public.business_daily (
 owner bigint not null check(owner>0), branch text not null check(branch ~ '^[0-9]{1,20}$'),
 day date not null, metrics jsonb not null check(jsonb_typeof(metrics)='object'),
 updated_at timestamptz not null default now(), primary key(owner,branch,day)
);
create table public.business_history (
 id bigint generated always as identity primary key, owner bigint not null,
 branch text not null, day date not null, metrics jsonb not null,
 recorded_at timestamptz not null default now()
);
create index business_history_owner_day on public.business_history(owner,branch,day,recorded_at desc);
create table public.business_sync (
 owner bigint not null, branch text not null, last_success timestamptz,
 last_error timestamptz, primary key(owner,branch)
);
create table public.business_notifications (
 owner bigint not null, branch text not null, kind text not null check(kind in ('daily','drop','failure')),
 day date not null, claimed_at timestamptz not null default now(), primary key(owner,branch,kind,day)
);
alter table public.business_daily enable row level security;
alter table public.business_history enable row level security;
alter table public.business_sync enable row level security;
alter table public.business_notifications enable row level security;
revoke all on public.business_daily,public.business_history,public.business_sync,public.business_notifications from public,anon,authenticated;
grant select,insert,update on public.business_daily,public.business_sync to service_role;
grant select,insert on public.business_history,public.business_notifications to service_role;
grant usage,select on sequence public.business_history_id_seq to service_role;

create function public.business_save(p_owner bigint,p_branch text,p_rows jsonb)
returns table(owner bigint,branch text) language plpgsql security invoker set search_path='' as $$
declare r jsonb; m jsonb; old jsonb; d date; h jsonb; n integer:=0;
begin
 if p_owner<=0 or p_branch !~ '^[0-9]{1,20}$' or jsonb_typeof(p_rows)!='array'
 or jsonb_array_length(p_rows)!=90 then raise exception 'Invalid business snapshot'; end if;
 perform pg_advisory_xact_lock(hashtextextended(p_owner::text || ':' || p_branch,0));
 for r in select value from jsonb_array_elements(p_rows) loop
  d:=(r->>'day')::date; m:=r->'metrics';
  if jsonb_typeof(m)!='object' or jsonb_array_length(m->'hours')!=24 then raise exception 'Invalid metrics'; end if;
  select jsonb_agg((value#>>'{}')::numeric order by ordinality) into h
  from jsonb_array_elements(m->'hours') with ordinality;
  m:=jsonb_build_object('total',(m->>'total')::numeric,'sales_total',(m->>'sales_total')::numeric,
   'returns_total',(m->>'returns_total')::numeric,'sales_count',(m->>'sales_count')::integer,
   'returns_count',(m->>'returns_count')::integer,'canceled_count',(m->>'canceled_count')::integer,
   'cost_fifo',(m->>'cost_fifo')::numeric,'cost_average',(m->>'cost_average')::numeric,'hours',h);
  if (m->>'total') is null or (m->>'sales_total') is null or (m->>'returns_total') is null
   or (m->>'sales_count') is null or (m->>'returns_count') is null or (m->>'canceled_count') is null
   or (m->>'total')::numeric != (m->>'sales_total')::numeric + (m->>'returns_total')::numeric
   or (m->>'sales_count')::integer<0 or (m->>'returns_count')::integer<0 or (m->>'canceled_count')::integer<0
   or (m->>'sales_total')::numeric<0 or (m->>'returns_total')::numeric>0
   or d<((now() at time zone 'Asia/Qyzylorda')::date-89) or d>(now() at time zone 'Asia/Qyzylorda')::date
  then raise exception 'Invalid daily totals'; end if;
  select b.metrics into old from public.business_daily b where b.owner=p_owner and b.branch=p_branch and b.day=d;
  if old is distinct from m then
   insert into public.business_history(owner,branch,day,metrics) values(p_owner,p_branch,d,m);
  end if;
  insert into public.business_daily(owner,branch,day,metrics) values(p_owner,p_branch,d,m)
   on conflict on constraint business_daily_pkey do update set metrics=excluded.metrics,updated_at=now();
  n:=n+1;
 end loop;
 if (select count(distinct value->>'day') from jsonb_array_elements(p_rows))!=90 then raise exception 'Duplicate days'; end if;
 insert into public.business_sync(owner,branch,last_success) values(p_owner,p_branch,now())
 on conflict on constraint business_sync_pkey do update set last_success=now(),last_error=null;
 return query select p_owner,p_branch;
end $$;
revoke all on function public.business_save(bigint,text,jsonb) from public,anon,authenticated;
grant execute on function public.business_save(bigint,text,jsonb) to service_role;

create function public.business_claim(p_owner bigint,p_branch text,p_kind text,p_day date)
returns table(owner bigint,branch text) language sql security invoker set search_path='' as $$
 insert into public.business_notifications(owner,branch,kind,day) values(p_owner,p_branch,p_kind,p_day)
 on conflict do nothing returning owner,branch;
$$;
revoke all on function public.business_claim(bigint,text,text,date) from public,anon,authenticated;
grant execute on function public.business_claim(bigint,text,text,date) to service_role;
commit;
