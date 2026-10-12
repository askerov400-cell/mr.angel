begin;
create or replace function public.business_save(p_owner bigint,p_branch text,p_rows jsonb)
returns table(owner bigint,branch text) language plpgsql security invoker set search_path='' as $$
declare r jsonb; m jsonb; old jsonb; d date; h jsonb; n integer:=0; e jsonb; c jsonb; v text;
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
  -- Optional for backwards compatibility with the previous deployed worker.
  e:=r->'metrics';
  c:=coalesce(e->'expense_categories','{}'::jsonb);
  if jsonb_typeof(c)!='object' then raise exception 'Invalid expense categories'; end if;
  if exists(select 1 from jsonb_each(c) where key !~ '^[0-9]{1,20}$'
     or (value#>>'{}')::numeric<0 or (value#>>'{}')::numeric::text in ('NaN','Infinity','-Infinity'))
  then raise exception 'Invalid expense category value'; end if;
  select coalesce(jsonb_object_agg(key,(value#>>'{}')::numeric),'{}'::jsonb) into c from jsonb_each(c);
  foreach v in array array['expenses_total','excluded_total','unknown_total','expenses_count','excluded_count','unknown_count'] loop
   if e->>v is not null and ((e->>v)::numeric<0 or (e->>v)::numeric::text in ('NaN','Infinity','-Infinity'))
    then raise exception 'Invalid expense total'; end if;
  end loop;
  if e->>'expenses_total' is not null and (
    e->>'expenses_count' is null or e->>'excluded_count' is null or e->>'unknown_count' is null
    or e->>'excluded_total' is null or e->>'unknown_total' is null
    or (e->>'expenses_total')::numeric != (select coalesce(sum((value#>>'{}')::numeric),0) from jsonb_each(c)))
  then raise exception 'Incomplete expense metrics'; end if;
  m:=m || jsonb_build_object('expenses_total',(e->>'expenses_total')::numeric,
    'expenses_count',(e->>'expenses_count')::integer,'excluded_total',(e->>'excluded_total')::numeric,
    'excluded_count',(e->>'excluded_count')::integer,'unknown_total',(e->>'unknown_total')::numeric,
    'unknown_count',(e->>'unknown_count')::integer,'expense_categories',c);
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

commit;
