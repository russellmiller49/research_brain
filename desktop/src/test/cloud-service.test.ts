import { expect, test, vi } from "vitest";
import { SupabaseCloudLibraryService } from "../cloud/service";

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
