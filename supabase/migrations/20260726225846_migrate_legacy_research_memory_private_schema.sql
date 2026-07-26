-- Early local builds used the generic `private` schema. Preserve their data
-- while moving only a recognizable Research Memory schema to its namespaced
-- production location. Fresh installs already use the target schema.

do $$
begin
  if to_regclass('private.article_pages') is null then
    return;
  end if;

  if to_regnamespace('research_memory_private') is not null then
    raise exception
      'Both private and research_memory_private contain Research Memory state';
  end if;

  if
    to_regclass('private.article_chunks') is null
    or to_regclass('private.cloud_connection_secrets') is null
    or to_regclass('private.cloud_oauth_states') is null
    or to_regprocedure('private.touch_sync_row()') is null
  then
    raise exception
      'The legacy private schema does not match the Research Memory inventory';
  end if;

  execute 'alter schema private rename to research_memory_private';
end;
$$;
