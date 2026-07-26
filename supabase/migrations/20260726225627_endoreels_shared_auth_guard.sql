-- Endoreels shares one Supabase Auth user pool with Research Memory.
-- Its learner-onboarding trigger predates app-scoped users and otherwise
-- creates an unrelated learner profile for every Research Memory signup.
--
-- Patch only the known trigger function when it exists. A dedicated
-- Research Memory project does not have this function, so this migration is
-- intentionally a no-op there.

do $$
declare
  function_oid regprocedure :=
    to_regprocedure('public.handle_new_learner_profile()');
  original_definition text;
  patched_definition text;
begin
  if function_oid is null then
    return;
  end if;

  original_definition := pg_get_functiondef(function_oid);

  if position('''research_memory''' in original_definition) > 0 then
    return;
  end if;

  patched_definition := replace(
    original_definition,
    'if coalesce(metadata ->> ''app_scope'', '''') = ''main_site'' then',
    'if coalesce(metadata ->> ''app_scope'', '''') in (''main_site'', ''research_memory'') then'
  );

  if patched_definition = original_definition then
    raise exception
      'Endoreels learner trigger no longer matches the reviewed definition';
  end if;

  execute patched_definition;
end;
$$;
