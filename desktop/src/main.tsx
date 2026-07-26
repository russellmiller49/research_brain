import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const cloudMode = import.meta.env.MODE === "cloud";
const RootApp = lazy(() =>
  cloudMode
    ? import("./cloud/CloudApp").then((module) => ({
        default: module.CloudApp,
      }))
    : import("./App").then((module) => ({ default: module.App })),
);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Suspense fallback={<div className="boot">Opening Research Memory…</div>}>
      <RootApp />
    </Suspense>
  </StrictMode>,
);
