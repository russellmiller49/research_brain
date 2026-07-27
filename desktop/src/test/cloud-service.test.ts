import { expect, test, vi } from "vitest";
import { SupabaseCloudLibraryService } from "../cloud/service";

test("uses native password auth with scoped signup and recovery redirects", async () => {
  const signInWithPassword = vi.fn(async () => ({ error: null }));
  const signUp = vi.fn(async () => ({
    data: { session: null },
    error: null,
  }));
  const resetPasswordForEmail = vi.fn(async () => ({ error: null }));
  const updateUser = vi.fn(async () => ({ error: null }));
  const service = Object.create(
    SupabaseCloudLibraryService.prototype,
  ) as SupabaseCloudLibraryService;
  Object.assign(service, {
    supabase: {
      auth: {
        resetPasswordForEmail,
        signInWithPassword,
        signUp,
        updateUser,
      },
    },
  });

  await service.signInWithPassword(
    "reader@example.test",
    "long-test-password",
  );
  const result = await service.signUpWithPassword(
    "new-reader@example.test",
    "long-test-password",
  );
  await service.requestPasswordReset("reader@example.test");
  await service.updatePassword("replacement-password");

  expect(signInWithPassword).toHaveBeenCalledWith({
    email: "reader@example.test",
    password: "long-test-password",
  });
  expect(signUp).toHaveBeenCalledWith({
    email: "new-reader@example.test",
    password: "long-test-password",
    options: expect.objectContaining({
      data: { app_scope: "research_memory" },
      emailRedirectTo: `${window.location.origin}/`,
    }),
  });
  expect(result).toEqual({ requiresEmailConfirmation: true });
  expect(resetPasswordForEmail).toHaveBeenCalledWith(
    "reader@example.test",
    { redirectTo: `${window.location.origin}/reset-password` },
  );
  expect(updateUser).toHaveBeenCalledWith({
    password: "replacement-password",
  });
});

test("turns a stopped local connector response into an actionable error", async () => {
  const service = Object.create(
    SupabaseCloudLibraryService.prototype,
  ) as SupabaseCloudLibraryService;
  Object.assign(service, {
    context: vi.fn(async () => ({})),
    supabase: {
      functions: {
        invoke: vi.fn(async () => ({
          data: null,
          error: {
            name: "FunctionsHttpError",
            message: "Edge Function returned a non-2xx status code",
            context: new Response(
              JSON.stringify({ message: "name resolution failed" }),
              {
                status: 503,
                headers: { "Content-Type": "application/json" },
              },
            ),
          },
        })),
      },
    },
  });

  await expect(service.connectDrive("google_drive")).rejects.toThrow(
    "The cloud-drive connector is stopped in this local build",
  );
});
