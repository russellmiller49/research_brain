-- PostgreSQL preserves PL/pgSQL source text when a schema is renamed. Repair the
-- five Research Memory functions created by the legacy migrations without
-- touching unrelated functions in a shared Supabase project.
do $migration$
declare
  function_signature text;
  function_oid oid;
  original_definition text;
  repaired_definition text;
begin
  if to_regnamespace('research_memory_private') is null then
    return;
  end if;

  foreach function_signature in array array[
    'public.search_library_chunks(uuid,text,integer)',
    'public.create_cloud_oauth_state(text,uuid,uuid,text,text,text,timestamptz)',
    'public.consume_cloud_oauth_state(text)',
    'public.upsert_cloud_connection_secret(uuid,uuid,uuid,text,timestamptz)',
    'public.read_cloud_connection_secret(uuid)'
  ]
  loop
    function_oid := to_regprocedure(function_signature);

    if function_oid is null then
      continue;
    end if;

    original_definition := pg_get_functiondef(function_oid);

    if position('research_memory_private.' in original_definition) > 0
       or position('private.' in original_definition) = 0 then
      continue;
    end if;

    repaired_definition := regexp_replace(
      original_definition,
      '(^|[^[:alnum:]_])private\.',
      '\1research_memory_private.',
      'g'
    );

    if repaired_definition = original_definition then
      raise exception
        'Could not repair legacy schema reference in %',
        function_signature;
    end if;

    execute repaired_definition;
  end loop;
end
$migration$;
