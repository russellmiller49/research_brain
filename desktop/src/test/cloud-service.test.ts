import { expect, test, vi } from "vitest";
import { SupabaseCloudLibraryService } from "../cloud/service";

test("tags new passwordless users for the shared Supabase project", async () => {
  const signInWithOtp = vi.fn(async () => ({ error: null }));
  const service = Object.create(
    SupabaseCloudLibraryService.prototype,
  ) as SupabaseCloudLibraryService;
  Object.assign(service, {
    supabase: {
      auth: { signInWithOtp },
    },
  });

  await service.sendMagicLink("reader@example.test");

  expect(signInWithOtp).toHaveBeenCalledWith({
    email: "reader@example.test",
    options: expect.objectContaining({
      data: { app_scope: "research_memory" },
    }),
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
