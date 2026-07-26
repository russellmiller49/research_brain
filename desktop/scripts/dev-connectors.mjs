import { existsSync } from "node:fs";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const desktopDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryDirectory = resolve(desktopDirectory, "..");
const environmentFile = resolve(
  repositoryDirectory,
  "supabase/functions/.env.local",
);
const executable = process.platform === "win32" ? "npx.cmd" : "npx";
const argumentsList = [
  "--yes",
  "supabase@2.109.1",
  "functions",
  "serve",
];

if (existsSync(environmentFile)) {
  argumentsList.push("--env-file", environmentFile);
} else {
  console.warn(
    "Cloud connector OAuth credentials are not configured. " +
      "The service will run and report setup status, but attaching a drive " +
      "requires supabase/functions/.env.local.",
  );
}

const child = spawn(executable, argumentsList, {
  cwd: repositoryDirectory,
  stdio: "inherit",
});

child.on("error", (error) => {
  console.error("Could not start the cloud connector service:", error.message);
  process.exitCode = 1;
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exitCode = code ?? 1;
});
