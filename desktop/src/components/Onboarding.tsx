import {
  Archive,
  ArrowLeft,
  ArrowRight,
  Check,
  Database,
  FolderOpen,
  LockKeyhole,
  Sparkles,
} from "lucide-react";
import { useState } from "react";
import { core } from "../lib/api";
import type { CoreStatus } from "../types";

export function Onboarding({
  status,
  onComplete,
}: {
  status: CoreStatus;
  onComplete: () => void;
}) {
  const [step, setStep] = useState(0);
  const [folderChosen, setFolderChosen] = useState(false);
  const [zoteroStarted, setZoteroStarted] = useState(false);
  const [modelStarted, setModelStarted] = useState(
    status.embedding_backend.startsWith("fastembed:"),
  );
  const [backupPassphrase, setBackupPassphrase] = useState("");
  const [backupCreated, setBackupCreated] = useState(false);
  const [privacyAccepted, setPrivacyAccepted] = useState(false);
  const [working, setWorking] = useState("");
  const [error, setError] = useState("");

  const perform = async (name: string, action: () => Promise<void>) => {
    setWorking(name);
    setError("");
    try {
      await action();
    } catch (value) {
      setError(value instanceof Error ? value.message : String(value));
    } finally {
      setWorking("");
    }
  };

  const steps = [
    {
      icon: FolderOpen,
      title: "Choose your literature",
      copy: "Research Memory makes immutable managed copies. Your originals and Zotero library are never modified.",
      content: (
        <div className="onboarding-actions">
          <button
            className="choice-card"
            disabled={Boolean(working)}
            onClick={() => {
              void perform("folder", async () => {
                const job = await core.chooseImportFolder();
                if (job) {
                  setFolderChosen(true);
                }
              });
            }}
          >
            <FolderOpen />
            <span><b>Select a folder</b><small>PDFs are copied into private content-addressed storage.</small></span>
            {folderChosen && <Check className="choice-check" />}
          </button>
          <button
            className="choice-card"
            disabled={Boolean(working)}
            onClick={() => {
              void perform("zotero", async () => {
                await core.importZotero();
                setZoteroStarted(true);
              });
            }}
          >
            <Database />
            <span><b>Connect Zotero</b><small>One-way through Zotero’s supported local read-only API.</small></span>
            {zoteroStarted && <Check className="choice-check" />}
          </button>
        </div>
      ),
    },
    {
      icon: Sparkles,
      title: "Install Recall Search",
      copy: "The pinned BGE model runs locally with ONNX. It never sends paper text or queries to a server.",
      content: (
        <div className="model-install-card">
          <Sparkles />
          <div>
            <b>BAAI/bge-small-en-v1.5 · quantized ONNX</b>
            <small>About 70 MB. Existing papers reindex in resumable background jobs.</small>
          </div>
          <button
            className="button primary"
            disabled={modelStarted || Boolean(working)}
            onClick={() => {
              void perform("model", async () => {
                await core.installModel();
                setModelStarted(true);
              });
            }}
          >
            {modelStarted ? "Installed or queued" : "Install model"}
          </button>
        </div>
      ),
    },
    {
      icon: Archive,
      title: "Protect your library",
      copy: "Create an encrypted portable backup now or later in Settings. Recovery verifies PDF hashes, annotations, collections, and the rebuildable search index.",
      content: (
        <div className="onboarding-actions">
          <label>
            Backup passphrase
            <input
              type="password"
              value={backupPassphrase}
              onChange={(event) => setBackupPassphrase(event.target.value)}
              placeholder="At least 12 characters"
              autoComplete="new-password"
            />
          </label>
          <button
            className="button primary"
            disabled={backupPassphrase.length < 12 || Boolean(working) || backupCreated}
            onClick={() => {
              void perform("backup", async () => {
                try {
                  const name = await core.chooseBackupDestination(backupPassphrase);
                  if (name) setBackupCreated(true);
                } finally {
                  setBackupPassphrase("");
                }
              });
            }}
          >
            {backupCreated ? <><Check /> Backup created</> : "Choose backup destination…"}
          </button>
          <div className="privacy-summary">
            <div><LockKeyhole /><span><b>Local by default</b><small>PDFs, notes, searches, and annotations stay on this Mac.</small></span></div>
            <div><Archive /><span><b>30-day app trash</b><small>Removing an article never deletes its source file.</small></span></div>
          </div>
        </div>
      ),
    },
    {
      icon: LockKeyhole,
      title: "Privacy boundaries",
      copy: "Online metadata is off until you opt in. Cloud AI is not part of this beta. Diagnostics exclude content and are disabled by default.",
      content: (
        <label className="consent-row">
          <input
            type="checkbox"
            checked={privacyAccepted}
            onChange={(event) => setPrivacyAccepted(event.target.checked)}
          />
          <span>
            I understand this beta is for legally obtained literature—not PHI, clinical records, autonomous recommendations, or validated systematic-review adjudication.
          </span>
        </label>
      ),
    },
  ];
  const current = steps[step]!;
  const Icon = current.icon;
  return (
    <div className="onboarding">
      <div className="onboarding-brand"><span className="brand-glyph">RM</span>Research Memory</div>
      <div className="onboarding-card">
        <div className="onboarding-progress">
          {steps.map((item, index) => (
            <span key={item.title} className={index <= step ? "active" : ""} />
          ))}
        </div>
        <div className="onboarding-icon"><Icon /></div>
        <span className="eyebrow">Setup {step + 1} of {steps.length}</span>
        <h1>{current.title}</h1>
        <p>{current.copy}</p>
        {error && <div className="error-banner" role="alert">{error}</div>}
        {current.content}
        <div className="onboarding-footer">
          <button className="button ghost" disabled={step === 0} onClick={() => setStep((value) => value - 1)}>
            <ArrowLeft size={17} /> Back
          </button>
          {step < steps.length - 1 ? (
            <button className="button primary" onClick={() => setStep((value) => value + 1)}>
              Continue <ArrowRight size={17} />
            </button>
          ) : (
            <button className="button primary" disabled={!privacyAccepted} onClick={onComplete}>
              Enter Research Memory <ArrowRight size={17} />
            </button>
          )}
        </div>
      </div>
      <small className="onboarding-footnote">macOS account security and FileVault are recommended.</small>
    </div>
  );
}
