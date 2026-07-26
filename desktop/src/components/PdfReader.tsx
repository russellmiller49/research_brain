import {
  ChevronLeft,
  ChevronRight,
  Download,
  FileDown,
  FolderPlus,
  Highlighter,
  ListTree,
  MessageSquareText,
  PanelLeftClose,
  PanelRightClose,
  Search,
  Trash2,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import {
  GlobalWorkerOptions,
  getDocument,
  TextLayer,
  type PDFDocumentProxy,
  type PDFPageProxy,
  type PageViewport,
  type RenderTask,
} from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { core, type ReaderCore } from "../lib/api";
import type {
  Annotation,
  ArticleDetail,
  BoundingBox,
  EntityId,
  Project,
  SearchHit,
} from "../types";

GlobalWorkerOptions.workerSrc = workerUrl;

interface PdfReaderProps {
  article: ArticleDetail;
  initialHit?: SearchHit;
  client?: ReaderCore;
  onClose: () => void;
  onArticleChanged: (article: ArticleDetail) => void;
  onTrashed: () => void;
}

interface PendingSelection {
  page: number;
  text: string;
  quadPoints: number[];
}

interface PasswordRequest {
  submit: (password: string) => void;
}

interface OutlineEntry {
  title: string;
  page: number;
  level: number;
}

function rectFromQuad(points: number[]) {
  const xs = points.filter((_, index) => index % 2 === 0);
  const ys = points.filter((_, index) => index % 2 === 1);
  return {
    x0: Math.min(...xs),
    y0: Math.min(...ys),
    x1: Math.max(...xs),
    y1: Math.max(...ys),
  };
}

function PdfPage({
  pdf,
  pageNumber,
  scale,
  activePage,
  sourceBoxes,
  annotations,
  onVisible,
  onSelection,
}: {
  pdf: PDFDocumentProxy;
  pageNumber: number;
  scale: number;
  activePage: number;
  sourceBoxes: BoundingBox[];
  annotations: Annotation[];
  onVisible: (page: number) => void;
  onSelection: (selection: PendingSelection | null) => void;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const textLayerRef = useRef<HTMLDivElement>(null);
  const [page, setPage] = useState<PDFPageProxy | null>(null);
  const [viewport, setViewport] = useState<PageViewport | null>(null);
  const [near, setNear] = useState(
    Math.abs(pageNumber - activePage) <= 2,
  );

  useEffect(() => {
    const host = hostRef.current;
    if (!host || typeof IntersectionObserver === "undefined") {
      setNear(true);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry) return;
        setNear(entry.isIntersecting);
        if (entry.isIntersecting) {
          onVisible(pageNumber);
        }
      },
      { rootMargin: "1100px 0px", threshold: 0.08 },
    );
    observer.observe(host);
    return () => observer.disconnect();
  }, [onVisible, pageNumber]);

  useEffect(() => {
    if (!near) {
      setPage(null);
      setViewport(null);
      textLayerRef.current?.replaceChildren();
      if (canvasRef.current) {
        canvasRef.current.width = 0;
        canvasRef.current.height = 0;
      }
      return;
    }
    let canceled = false;
    void pdf.getPage(pageNumber).then((loaded) => {
      if (!canceled) setPage(loaded);
    });
    return () => {
      canceled = true;
    };
  }, [near, pageNumber, pdf]);

  useEffect(() => {
    if (!page || !canvasRef.current || !textLayerRef.current) return;
    const nextViewport = page.getViewport({ scale });
    setViewport(nextViewport);
    const canvas = canvasRef.current;
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.floor(nextViewport.width * ratio);
    canvas.height = Math.floor(nextViewport.height * ratio);
    canvas.style.width = `${nextViewport.width}px`;
    canvas.style.height = `${nextViewport.height}px`;
    const render = page.render({
      canvas,
      canvasContext: context,
      viewport: nextViewport,
      transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
    });
    void render.promise.catch(() => {});

    const layer = textLayerRef.current;
    layer.replaceChildren();
    const textLayer = new TextLayer({
      textContentSource: page.streamTextContent(),
      container: layer,
      viewport: nextViewport,
    });
    void textLayer.render().catch(() => {});
    return () => {
      render.cancel();
      textLayer.cancel();
    };
  }, [page, scale]);

  const projected = useMemo(() => {
    if (!viewport) return [];
    const values = [
      ...sourceBoxes.map((box) => ({
        ...box,
        source: true,
        id: "source",
        color: "#F4C95D",
      })),
      ...annotations
        .filter((annotation) => annotation.quad_points.length >= 8)
        .map((annotation) => ({
          ...rectFromQuad(annotation.quad_points),
          source: false,
          id: annotation.id,
          color: annotation.color,
        })),
    ];
    return values.map((value) => {
      const [left, top, right, bottom] = viewport.convertToViewportRectangle([
        value.x0,
        value.y0,
        value.x1,
        value.y1,
      ]);
      return {
        ...value,
        left: Math.min(left, right),
        top: Math.min(top, bottom),
        width: Math.abs(right - left),
        height: Math.abs(bottom - top),
      };
    });
  }, [annotations, sourceBoxes, viewport]);

  const captureSelection = () => {
    const selection = window.getSelection();
    const host = hostRef.current;
    if (!selection || selection.isCollapsed || !host || !viewport) {
      onSelection(null);
      return;
    }
    const range = selection.getRangeAt(0);
    if (!host.contains(range.commonAncestorContainer)) return;
    const hostRect = host.getBoundingClientRect();
    const quadPoints: number[] = [];
    for (const rectangle of Array.from(range.getClientRects())) {
      if (rectangle.width < 1 || rectangle.height < 1) continue;
      const [x0, yTop] = viewport.convertToPdfPoint(
        rectangle.left - hostRect.left,
        rectangle.top - hostRect.top,
      );
      const [x1, yBottom] = viewport.convertToPdfPoint(
        rectangle.right - hostRect.left,
        rectangle.bottom - hostRect.top,
      );
      quadPoints.push(x0, yTop, x1, yTop, x0, yBottom, x1, yBottom);
    }
    if (quadPoints.length) {
      onSelection({
        page: pageNumber,
        text: selection.toString().trim(),
        quadPoints,
      });
    }
  };

  const defaultHeight = 792 * scale;
  return (
    <div
      ref={hostRef}
      className="pdf-page"
      data-page={pageNumber}
      style={{
        width: viewport?.width ?? 612 * scale,
        minHeight: viewport?.height ?? defaultHeight,
      }}
      onMouseUp={captureSelection}
      aria-label={`PDF page ${pageNumber}`}
    >
      {near ? (
        <>
          <canvas ref={canvasRef} />
          <div ref={textLayerRef} className="pdf-text-layer" />
          <div className="pdf-highlight-layer" aria-hidden="true">
            {projected.map((box, index) => (
              <span
                key={`${box.id}-${index}`}
                className={box.source ? "source-highlight" : "user-highlight"}
                style={{
                  left: box.left,
                  top: box.top,
                  width: box.width,
                  height: box.height,
                  background: box.source ? undefined : `${box.color}66`,
                }}
              />
            ))}
          </div>
        </>
      ) : (
        <div className="page-skeleton" />
      )}
      <span className="page-number">{pageNumber}</span>
    </div>
  );
}

function Thumbnail({
  pdf,
  pageNumber,
  current,
  onSelect,
}: {
  pdf: PDFDocumentProxy;
  pageNumber: number;
  current: boolean;
  onSelect: () => void;
}) {
  const hostRef = useRef<HTMLButtonElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [near, setNear] = useState(false);
  useEffect(() => {
    const host = hostRef.current;
    if (!host || typeof IntersectionObserver === "undefined") {
      setNear(true);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry) setNear(entry.isIntersecting);
      },
      { rootMargin: "700px 0px" },
    );
    observer.observe(host);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!near) {
      if (canvasRef.current) {
        canvasRef.current.width = 0;
        canvasRef.current.height = 0;
      }
      return;
    }
    let render: RenderTask | undefined;
    void pdf.getPage(pageNumber).then((page) => {
      const viewport = page.getViewport({ scale: 0.18 });
      const canvas = canvasRef.current;
      const context = canvas?.getContext("2d");
      if (!canvas || !context) return;
      canvas.width = Math.ceil(viewport.width);
      canvas.height = Math.ceil(viewport.height);
      render = page.render({ canvas, canvasContext: context, viewport });
      void render.promise.catch(() => {});
    });
    return () => render?.cancel();
  }, [near, pageNumber, pdf]);
  return (
    <button
      ref={hostRef}
      className={`thumbnail ${current ? "current" : ""}`}
      onClick={onSelect}
      aria-label={`Go to page ${pageNumber}`}
    >
      {near ? <canvas ref={canvasRef} /> : <span className="thumbnail-placeholder" />}
      <span>{pageNumber}</span>
    </button>
  );
}

export function PdfReader({
  article,
  initialHit,
  client = core,
  onClose,
  onArticleChanged,
  onTrashed,
}: PdfReaderProps) {
  const compactReader =
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(max-width: 760px)").matches;
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [assetUrl, setAssetUrl] = useState("");
  const [loadError, setLoadError] = useState("");
  const [passwordRequest, setPasswordRequest] = useState<PasswordRequest | null>(null);
  const [passwordInput, setPasswordInput] = useState("");
  const [page, setPage] = useState(initialHit?.page_number ?? 1);
  const [zoom, setZoom] = useState(compactReader ? 0.85 : 1.15);
  const [leftOpen, setLeftOpen] = useState(!compactReader);
  const [leftMode, setLeftMode] = useState<"pages" | "outline">("pages");
  const [outline, setOutline] = useState<OutlineEntry[]>([]);
  const [leftWidth, setLeftWidth] = useState(150);
  const [rightOpen, setRightOpen] = useState(!compactReader);
  const [rightWidth, setRightWidth] = useState(310);
  const [findOpen, setFindOpen] = useState(false);
  const [findQuery, setFindQuery] = useState("");
  const [findStatus, setFindStatus] = useState("");
  const [selection, setSelection] = useState<PendingSelection | null>(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [notice, setNotice] = useState("");
  const [whySaved, setWhySaved] = useState(article.why_saved);
  const [userSummary, setUserSummary] = useState(article.user_summary);
  const [metadataTitle, setMetadataTitle] = useState(article.title);
  const [metadataAuthors, setMetadataAuthors] = useState(article.authors);
  const [metadataJournal, setMetadataJournal] = useState(article.journal);
  const [metadataYear, setMetadataYear] = useState(
    article.publication_year?.toString() ?? "",
  );
  const [metadataDoi, setMetadataDoi] = useState(article.doi);
  const [metadataPmid, setMetadataPmid] = useState(article.pmid);
  const scrollRef = useRef<HTMLDivElement>(null);
  const findRef = useRef<HTMLInputElement>(null);
  const sessionPasswordRef = useRef("");
  const primaryAsset =
    article.assets.find((item) => item.is_primary && item.availability === "available")
    ?? article.assets.find((item) => item.availability === "available")
    ?? article.assets[0];
  const [selectedAssetId, setSelectedAssetId] = useState<EntityId | null>(
    initialHit?.asset_id ?? primaryAsset?.id ?? null,
  );
  const asset =
    article.assets.find(
      (item) => item.id === selectedAssetId && item.availability === "available",
    ) ?? primaryAsset;
  const assetAnnotations = useMemo(
    () => article.annotations.filter((annotation) => annotation.asset_id === asset?.id),
    [article.annotations, asset?.id],
  );

  useEffect(() => {
    setSelectedAssetId(initialHit?.asset_id ?? primaryAsset?.id ?? null);
  }, [article.id, initialHit?.asset_id, primaryAsset?.id]);

  useEffect(() => {
    if (!asset) return;
    let task: ReturnType<typeof getDocument> | null = null;
    let canceled = false;
    void client.assetUrl(asset.id).then((url) => {
      if (canceled) return;
      setAssetUrl(url);
      task = getDocument(url);
      task.onPassword = (submit: (password: string) => void) => {
        setPasswordRequest({ submit });
      };
      void task.promise
        .then((loaded) => {
          setPdf(loaded);
          setLoadError("");
          if (
            article.extraction_status === "password_required"
            && sessionPasswordRef.current
          ) {
            const password = sessionPasswordRef.current;
            sessionPasswordRef.current = "";
            void client.unlockArticle(article.id, password).then(() => {
              setNotice("Password accepted. Private indexing was queued.");
            });
          }
        })
        .catch(() => {
          setLoadError("This PDF could not be opened. Review its import status in Imports & Jobs.");
        });
    }).catch(() => {
      setLoadError("The managed PDF is unavailable.");
    });
    return () => {
      canceled = true;
      sessionPasswordRef.current = "";
      void task?.destroy();
    };
  }, [article.extraction_status, article.id, asset, client]);

  useEffect(() => {
    void client.projects().then(setProjects).catch(() => setProjects([]));
  }, [client]);

  useEffect(() => {
    setWhySaved(article.why_saved);
    setUserSummary(article.user_summary);
    setMetadataTitle(article.title);
    setMetadataAuthors(article.authors);
    setMetadataJournal(article.journal);
    setMetadataYear(article.publication_year?.toString() ?? "");
    setMetadataDoi(article.doi);
    setMetadataPmid(article.pmid);
  }, [
    article.authors,
    article.doi,
    article.id,
    article.journal,
    article.pmid,
    article.publication_year,
    article.title,
    article.user_summary,
    article.why_saved,
  ]);

  useEffect(() => {
    if (!pdf) return;
    let canceled = false;
    const loadOutline = async () => {
      const entries: OutlineEntry[] = [];
      const nodes = await pdf.getOutline();
      const visit = async (
        values: NonNullable<typeof nodes>,
        level: number,
      ): Promise<void> => {
        for (const node of values) {
          let targetPage = 0;
          const destination = typeof node.dest === "string"
            ? await pdf.getDestination(node.dest)
            : node.dest;
          if (Array.isArray(destination) && destination[0]) {
            const reference = destination[0];
            if (typeof reference === "object") {
              try {
                targetPage = await pdf.getPageIndex(
                  reference as Parameters<PDFDocumentProxy["getPageIndex"]>[0],
                ) + 1;
              } catch {
                targetPage = 0;
              }
            } else if (typeof reference === "number") {
              targetPage = reference + 1;
            }
          }
          if (targetPage) {
            entries.push({
              title: node.title || `Page ${targetPage}`,
              page: targetPage,
              level,
            });
          }
          if (node.items.length) await visit(node.items, level + 1);
        }
      };
      if (nodes) await visit(nodes, 0);
      if (!canceled) setOutline(entries);
    };
    void loadOutline();
    return () => {
      canceled = true;
    };
  }, [pdf]);

  const goToPage = useCallback((target: number) => {
    const bounded = Math.max(1, Math.min(target, pdf?.numPages ?? target));
    setPage(bounded);
    scrollRef.current
      ?.querySelector(`[data-page="${bounded}"]`)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [pdf?.numPages]);

  const beginResize = (
    side: "left" | "right",
    event: ReactPointerEvent<HTMLDivElement>,
  ) => {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = side === "left" ? leftWidth : rightWidth;
    const move = (pointer: PointerEvent) => {
      const delta = side === "left"
        ? pointer.clientX - startX
        : startX - pointer.clientX;
      const next = Math.max(
        side === "left" ? 118 : 250,
        Math.min(side === "left" ? 300 : 480, startWidth + delta),
      );
      if (side === "left") setLeftWidth(next);
      else setRightWidth(next);
    };
    const finish = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish, { once: true });
  };

  useEffect(() => {
    if (!pdf || !initialHit?.page_number) return;
    const frame = requestAnimationFrame(() => goToPage(initialHit.page_number ?? 1));
    return () => cancelAnimationFrame(frame);
  }, [goToPage, initialHit?.page_number, pdf]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "f") {
        event.preventDefault();
        setFindOpen(true);
        requestAnimationFrame(() => findRef.current?.focus());
      } else if (event.key === "Escape") {
        if (findOpen) setFindOpen(false);
        else onClose();
      } else if (event.key === "PageDown") {
        event.preventDefault();
        goToPage(page + 1);
      } else if (event.key === "PageUp") {
        event.preventDefault();
        goToPage(page - 1);
      } else if ((event.metaKey || event.ctrlKey) && event.key === "=") {
        setZoom((value) => Math.min(2.5, value + 0.1));
      } else if ((event.metaKey || event.ctrlKey) && event.key === "-") {
        setZoom((value) => Math.max(0.6, value - 0.1));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [findOpen, goToPage, onClose, page]);

  const findInDocument = async () => {
    if (!pdf || !findQuery.trim()) return;
    setFindStatus("Searching…");
    const needle = findQuery.trim().toLowerCase();
    for (let index = 1; index <= pdf.numPages; index += 1) {
      const pdfPage = await pdf.getPage(index);
      const text = await pdfPage.getTextContent();
      const joined = text.items
        .map((item) => ("str" in item ? item.str : ""))
        .join(" ")
        .toLowerCase();
      if (joined.includes(needle)) {
        goToPage(index);
        setFindStatus(`Found on page ${index}`);
        return;
      }
    }
    setFindStatus("No match");
  };

  const saveSelection = async (annotationType: "highlight" | "comment") => {
    if (!selection || !asset) return;
    setBusy(true);
    try {
      const annotation = await client.createAnnotation(article.id, {
        asset_id: asset.id,
        page_number: selection.page,
        annotation_type: annotationType,
        color: annotationType === "highlight" ? "#F4C95D" : "#74B8A7",
        quad_points: selection.quadPoints,
        selected_text: selection.text,
        context_hash: "",
        comment,
      });
      onArticleChanged({
        ...article,
        annotations: [...article.annotations, annotation],
      });
      setSelection(null);
      setComment("");
      window.getSelection()?.removeAllRanges();
    } finally {
      setBusy(false);
    }
  };

  const sourcePage = initialHit?.page_number;
  const safeTitle = article.title
    .replace(/[/:*?"<>|]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 70) || "Research Memory article";
  const exportArticle = async (
    type: "markdown" | "ris" | "bibtex" | "xfdf" | "annotated_pdf",
    extension: string,
  ) => {
    if (!asset) return;
    try {
      const name = await client.exportArticle(
        article.id,
        asset.id,
        type,
        `${safeTitle}.${extension}`,
      );
      if (name) setNotice(`Exported ${name}`);
    } catch (value) {
      setNotice(
        `Could not export: ${value instanceof Error ? value.message : String(value)}`,
      );
    }
  };
  if (!asset) {
    return (
      <div className="reader-overlay">
        <div className="reader-empty">
          <h2>PDF unavailable</h2>
          <p>This article has no available managed asset.</p>
          <button className="button primary" onClick={onClose}>Close</button>
        </div>
      </div>
    );
  }

  return (
    <div className="reader-overlay" role="dialog" aria-label={`Reader: ${article.title}`}>
      <header className="reader-header">
        <button className="icon-button" onClick={onClose} aria-label="Close reader">
          <X size={19} />
        </button>
        <div className="reader-title">
          <strong>{article.title}</strong>
          {article.assets.length > 1 ? (
            <select
              aria-label="PDF version"
              value={asset.id}
              onChange={(event) => {
                const selected = article.assets.find(
                  (item) => String(item.id) === event.target.value,
                );
                setSelectedAssetId(selected?.id ?? null);
                setPage(1);
                setSelection(null);
              }}
            >
              {article.assets.map((item) => (
                <option
                  key={item.id}
                  value={item.id}
                  disabled={item.availability !== "available"}
                >
                  {item.version_label || "Version"}{item.is_primary ? " · Primary" : ""} · {item.file_name}
                  {item.availability !== "available" ? " · Missing" : ""}
                </option>
              ))}
            </select>
          ) : (
            <span>{article.authors || asset.file_name}</span>
          )}
        </div>
        <div className="reader-controls">
          <button className="icon-button" onClick={() => setLeftOpen((value) => !value)} aria-label="Toggle thumbnails">
            <PanelLeftClose size={18} />
          </button>
          <button className="icon-button" onClick={() => goToPage(page - 1)} aria-label="Previous page">
            <ChevronLeft size={18} />
          </button>
          <label className="page-control">
            <span className="sr-only">Current page</span>
            <input
              value={page}
              inputMode="numeric"
              onChange={(event) => setPage(Number(event.target.value) || 1)}
              onBlur={() => goToPage(page)}
            />
            <span>/ {pdf?.numPages ?? article.page_count}</span>
          </label>
          <button className="icon-button" onClick={() => goToPage(page + 1)} aria-label="Next page">
            <ChevronRight size={18} />
          </button>
          <button className="icon-button" onClick={() => setZoom((value) => Math.max(0.6, value - 0.1))} aria-label="Zoom out">
            <ZoomOut size={18} />
          </button>
          <span className="zoom-label">{Math.round(zoom * 100)}%</span>
          <button className="icon-button" onClick={() => setZoom((value) => Math.min(2.5, value + 0.1))} aria-label="Zoom in">
            <ZoomIn size={18} />
          </button>
          <button className="icon-button" onClick={() => setFindOpen((value) => !value)} aria-label="Find in document">
            <Search size={18} />
          </button>
          <a className="icon-button" href={assetUrl} download={asset.file_name} aria-label="Download managed copy">
            <Download size={18} />
          </a>
          <button className="icon-button" onClick={() => setRightOpen((value) => !value)} aria-label="Toggle context panel">
            <PanelRightClose size={18} />
          </button>
        </div>
      </header>

      {findOpen && (
        <form
          className="reader-find"
          onSubmit={(event) => {
            event.preventDefault();
            void findInDocument();
          }}
        >
          <Search size={16} />
          <input
            ref={findRef}
            value={findQuery}
            onChange={(event) => setFindQuery(event.target.value)}
            placeholder="Find in this PDF"
          />
          <button className="button secondary" disabled={!findQuery.trim()}>
            Find
          </button>
          <span>{findStatus}</span>
          <button type="button" className="icon-button" onClick={() => setFindOpen(false)} aria-label="Close find">
            <X size={16} />
          </button>
        </form>
      )}

      <div
        className={`reader-grid ${leftOpen ? "" : "left-closed"} ${rightOpen ? "" : "right-closed"}`}
        style={{
          gridTemplateColumns: [
            leftOpen ? `${leftWidth}px 5px` : "",
            "minmax(0, 1fr)",
            rightOpen ? `5px ${rightWidth}px` : "",
          ].filter(Boolean).join(" "),
        }}
      >
        {leftOpen && (
          <aside className="thumbnail-pane" aria-label="Page thumbnails">
            <div className="reader-left-tabs">
              <button
                className={leftMode === "pages" ? "active" : ""}
                onClick={() => setLeftMode("pages")}
              >
                Pages
              </button>
              <button
                className={leftMode === "outline" ? "active" : ""}
                onClick={() => setLeftMode("outline")}
              >
                <ListTree size={13} /> Outline
              </button>
            </div>
            {leftMode === "pages" && pdf &&
              Array.from({ length: pdf.numPages }, (_, index) => (
                <Thumbnail
                  key={index + 1}
                  pdf={pdf}
                  pageNumber={index + 1}
                  current={page === index + 1}
                  onSelect={() => goToPage(index + 1)}
                />
              ))}
            {leftMode === "outline" && (
              <div className="outline-list">
                {outline.map((entry, index) => (
                  <button
                    key={`${entry.page}-${index}`}
                    style={{ paddingLeft: 8 + entry.level * 12 }}
                    onClick={() => goToPage(entry.page)}
                  >
                    <span>{entry.title}</span>
                    <small>{entry.page}</small>
                  </button>
                ))}
                {!outline.length && <p>This PDF has no outline.</p>}
              </div>
            )}
          </aside>
        )}
        {leftOpen && (
          <div
            className="reader-resizer"
            role="separator"
            aria-label="Resize page navigation"
            aria-orientation="vertical"
            tabIndex={0}
            onPointerDown={(event) => beginResize("left", event)}
            onKeyDown={(event) => {
              if (event.key === "ArrowLeft") setLeftWidth((value) => Math.max(118, value - 10));
              if (event.key === "ArrowRight") setLeftWidth((value) => Math.min(300, value + 10));
            }}
          />
        )}
        <main className="pdf-scroll" ref={scrollRef}>
          {pdf ? (
            Array.from({ length: pdf.numPages }, (_, index) => {
              const pageNumber = index + 1;
              return (
                <PdfPage
                  key={pageNumber}
                  pdf={pdf}
                  pageNumber={pageNumber}
                  scale={zoom}
                  activePage={page}
                  sourceBoxes={
                    sourcePage === pageNumber
                      && (!initialHit?.asset_id || initialHit.asset_id === asset.id)
                      ? initialHit?.bounding_boxes ?? []
                      : []
                  }
                  annotations={assetAnnotations.filter(
                    (annotation) => annotation.page_number === pageNumber,
                  )}
                  onVisible={setPage}
                  onSelection={setSelection}
                />
              );
            })
          ) : (
            <div className="reader-loading">
              {!loadError && <span className="spinner" />}
              {loadError || "Loading PDF securely…"}
            </div>
          )}
        </main>
        {rightOpen && (
          <div
            className="reader-resizer"
            role="separator"
            aria-label="Resize context panel"
            aria-orientation="vertical"
            tabIndex={0}
            onPointerDown={(event) => beginResize("right", event)}
            onKeyDown={(event) => {
              if (event.key === "ArrowLeft") setRightWidth((value) => Math.min(480, value + 10));
              if (event.key === "ArrowRight") setRightWidth((value) => Math.max(250, value - 10));
            }}
          />
        )}
        {rightOpen && (
          <aside className="context-pane">
            {article.review_state !== "ready" && (
              <section className="review-state">
                <span className="eyebrow">Needs review</span>
                <b>{article.review_state.replaceAll("_", " ")}</b>
                {article.metadata_conflicts.map((conflict, index) => (
                  <div className="conflict-detail" key={index}>
                    <p>{String(conflict.reason ?? conflict.kind ?? "Metadata conflict")}</p>
                    {conflict.field != null && (
                      <small>
                        Local: {String(conflict.local_value ?? "—")} · Candidate: {String(conflict.candidate_value ?? "—")}
                      </small>
                    )}
                    {Array.isArray(conflict.article_ids) && (
                      <small>Possible matches: {conflict.article_ids.map(String).join(", ")}</small>
                    )}
                  </div>
                ))}
                {["possible_duplicate", "metadata_conflict", "multi_article"].includes(article.review_state) && (
                  <button
                    className="button secondary"
                    disabled={busy}
                    onClick={() => {
                      setBusy(true);
                      const resolution = article.review_state === "multi_article"
                        ? "keep_as_single_article"
                        : "accept_as_separate_article";
                      void client.resolveArticleReview(article.id, resolution)
                        .then((updated) => {
                          onArticleChanged(updated);
                          setNotice("Review decision saved.");
                        })
                        .catch((value) => {
                          setNotice(`Could not save review: ${value instanceof Error ? value.message : String(value)}`);
                        })
                        .finally(() => setBusy(false));
                    }}
                  >
                    {article.review_state === "multi_article"
                      ? "Keep this PDF as one article"
                      : "Accept metadata and keep separate"}
                  </button>
                )}
              </section>
            )}
            {initialHit && (!initialHit.asset_id || initialHit.asset_id === asset.id) && (
              <section className="source-passage">
                <span className="eyebrow">Opened from Recall Search · page {initialHit.page_number}</span>
                <blockquote>{initialHit.snippet}</blockquote>
                <div className="reason-row">
                  {initialHit.match_reasons.map((reason) => (
                    <span key={reason.code}>{reason.label}</span>
                  ))}
                </div>
              </section>
            )}
            <section>
              <div className="pane-heading">
                <div>
                  <span className="eyebrow">Personal context</span>
                  <h3>Highlights & comments</h3>
                </div>
                <button
                  className="icon-button"
                  aria-label="Bookmark current page"
                  onClick={() => {
                    void client.createAnnotation(article.id, {
                      asset_id: asset.id,
                      page_number: page,
                      annotation_type: "bookmark",
                      color: "#74B8A7",
                      quad_points: [],
                      selected_text: "",
                      context_hash: "",
                      comment: `Bookmark on page ${page}`,
                    }).then((annotation) =>
                      onArticleChanged({
                        ...article,
                        annotations: [...article.annotations, annotation],
                      }),
                    );
                  }}
                >
                  <MessageSquareText size={17} />
                </button>
              </div>
              <div className="annotation-list">
                {assetAnnotations.map((annotation) => (
                  <div
                    className="annotation-card"
                    key={annotation.id}
                  >
                    <span
                      className="annotation-swatch"
                      style={{ background: annotation.color }}
                    />
                    <button onClick={() => goToPage(annotation.page_number)}>
                      <b>Page {annotation.page_number}</b>
                      <small>{annotation.comment || annotation.selected_text || "Bookmark"}</small>
                    </button>
                    <button
                      className="annotation-delete"
                      aria-label={`Delete annotation on page ${annotation.page_number}`}
                      onClick={() => {
                        void client.deleteAnnotation(article.id, annotation.id).then(() => {
                          onArticleChanged({
                            ...article,
                            annotations: article.annotations.filter(
                              (item) => item.id !== annotation.id,
                            ),
                          });
                        });
                      }}
                    >
                      <X size={13} />
                    </button>
                  </div>
                ))}
                {!assetAnnotations.length && (
                  <p className="muted">Select text in the document to create a private highlight.</p>
                )}
              </div>
            </section>
            <section className="personal-note personal-context-editor">
              <span className="eyebrow">Why you saved this</span>
              <textarea
                value={whySaved}
                maxLength={50_000}
                onChange={(event) => setWhySaved(event.target.value)}
                placeholder="The detail you expect to remember later…"
              />
              <span className="eyebrow">Your summary</span>
              <textarea
                value={userSummary}
                maxLength={100_000}
                onChange={(event) => setUserSummary(event.target.value)}
                placeholder="Optional private summary"
              />
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => {
                  setBusy(true);
                  void client.updateArticle(article.id, {
                    why_saved: whySaved,
                    user_summary: userSummary,
                  }).then((updated) => {
                    onArticleChanged(updated);
                    setNotice("Personal context saved.");
                  }).catch((value) => {
                    setNotice(`Could not save context: ${value instanceof Error ? value.message : String(value)}`);
                  }).finally(() => setBusy(false));
                }}
              >
                Save context
              </button>
            </section>
            <section>
              <details className="metadata-editor">
                <summary>Bibliographic metadata</summary>
                <label>Title<input value={metadataTitle} maxLength={1_000} onChange={(event) => setMetadataTitle(event.target.value)} /></label>
                <label>Authors<input value={metadataAuthors} maxLength={2_000} onChange={(event) => setMetadataAuthors(event.target.value)} /></label>
                <label>Journal<input value={metadataJournal} maxLength={500} onChange={(event) => setMetadataJournal(event.target.value)} /></label>
                <div className="metadata-short-fields">
                  <label>Year<input value={metadataYear} inputMode="numeric" maxLength={4} onChange={(event) => setMetadataYear(event.target.value.replace(/\D/g, ""))} /></label>
                  <label>PMID<input value={metadataPmid} maxLength={20} onChange={(event) => setMetadataPmid(event.target.value)} /></label>
                </div>
                <label>DOI<input value={metadataDoi} maxLength={500} onChange={(event) => setMetadataDoi(event.target.value)} /></label>
                <button
                  className="button secondary"
                  disabled={busy || !metadataTitle.trim()}
                  onClick={() => {
                    setBusy(true);
                    void client.updateArticle(article.id, {
                      title: metadataTitle.trim(),
                      authors: metadataAuthors.trim(),
                      journal: metadataJournal.trim(),
                      publication_year: metadataYear ? Number(metadataYear) : null,
                      doi: metadataDoi.trim(),
                      pmid: metadataPmid.trim(),
                    }).then((updated) => {
                      onArticleChanged(updated);
                      setNotice("Bibliographic metadata saved.");
                    }).catch((value) => {
                      setNotice(`Could not save metadata: ${value instanceof Error ? value.message : String(value)}`);
                    }).finally(() => setBusy(false));
                  }}
                >
                  Save metadata
                </button>
              </details>
            </section>
            <section>
              <span className="eyebrow">Project</span>
              <div className="project-picker">
                <select
                  value={projectId}
                  onChange={(event) => setProjectId(event.target.value)}
                  aria-label="Choose project"
                >
                  <option value="">Choose a project…</option>
                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>{project.name}</option>
                  ))}
                </select>
                <button
                  className="button secondary"
                  disabled={!projectId}
                  onClick={() => {
                    const selectedProject = projects.find(
                      (project) => String(project.id) === projectId,
                    );
                    if (!selectedProject) return;
                    void client.addProjectArticle(selectedProject.id, article.id).then(() => {
                      setNotice("Added to project.");
                    });
                  }}
                >
                  <FolderPlus size={15} /> Add
                </button>
              </div>
            </section>
            <section>
              <span className="eyebrow">Export a new copy</span>
              <div className="export-grid">
                <button onClick={() => void exportArticle("markdown", "md")}>Markdown</button>
                <button onClick={() => void exportArticle("ris", "ris")}>RIS</button>
                <button onClick={() => void exportArticle("bibtex", "bib")}>BibTeX</button>
                <button onClick={() => void exportArticle("xfdf", "xfdf")}>XFDF</button>
                <button onClick={() => void exportArticle("annotated_pdf", "pdf")}>
                  <FileDown size={14} /> Annotated PDF
                </button>
              </div>
              {notice && <p className="reader-notice">{notice}</p>}
            </section>
            <section className="danger-zone">
              <span className="eyebrow">Library record</span>
              <p>Remove this managed copy from the library. Your source PDF is never changed.</p>
              <button
                className="button danger"
                disabled={busy}
                onClick={() => {
                  setBusy(true);
                  void client.trashArticle(article.id, article.title)
                    .then((trashed) => {
                      if (trashed) onTrashed();
                    })
                    .catch((value) => {
                      setNotice(`Could not move paper to Trash: ${value instanceof Error ? value.message : String(value)}`);
                    })
                    .finally(() => setBusy(false));
                }}
              >
                <Trash2 size={15} /> Move to Trash
              </button>
            </section>
          </aside>
        )}
      </div>

      {selection && (
        <div className="selection-toolbar" role="toolbar" aria-label="Selected text actions">
          <Highlighter size={17} />
          <span>{selection.text.slice(0, 80) || "Selected passage"}</span>
          <input
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            placeholder="Optional comment"
            aria-label="Highlight comment"
          />
          <button className="button secondary" disabled={busy} onClick={() => void saveSelection("highlight")}>
            Highlight
          </button>
          <button className="button primary" disabled={busy} onClick={() => void saveSelection("comment")}>
            Comment
          </button>
          <button className="icon-button" onClick={() => setSelection(null)} aria-label="Cancel selection">
            <X size={16} />
          </button>
        </div>
      )}
      {passwordRequest && (
        <form
          className="password-dialog"
          role="dialog"
          aria-modal="true"
          aria-label="Enter PDF password"
          onSubmit={(event) => {
            event.preventDefault();
            if (!passwordInput) return;
            sessionPasswordRef.current = passwordInput;
            passwordRequest.submit(passwordInput);
            setPasswordInput("");
            setPasswordRequest(null);
          }}
        >
          <span className="eyebrow">Encrypted PDF</span>
          <h2>Password required</h2>
          <p>The password is used only for this session and is never written to disk.</p>
          <input
            autoFocus
            type="password"
            value={passwordInput}
            onChange={(event) => setPasswordInput(event.target.value)}
            autoComplete="off"
            aria-label="PDF password"
          />
          <div className="button-row">
            <button type="button" className="button secondary" onClick={onClose}>Cancel</button>
            <button className="button primary" disabled={!passwordInput}>Unlock</button>
          </div>
        </form>
      )}
    </div>
  );
}
