import type {
  ArticleDetail,
  ArticlePage,
  ArticleSummary,
  CoreStatus,
  ImportJob,
  PersonalizedTaxonomyTree,
  Project,
  SearchHit,
  SpecialtyPackSummary,
  TaxonomyCatalogPage,
  TaxonomyNode,
  TrashArticle,
} from "../types";

const now = new Date().toISOString();

const articles: ArticleSummary[] = [
  {
    id: 1,
    title: "Prospective Evaluation of Robotic Bronchoscopy for Peripheral Pulmonary Lesions",
    authors: "Amelia Chen, Marcus Rivera, Priya Shah",
    journal: "Journal of Interventional Pulmonology",
    publication_year: 2024,
    source_type: "prospective_cohort",
    reading_status: "reading",
    importance: 4,
    page_count: 12,
    why_saved: "Navigation success was much higher than the strict diagnostic endpoint.",
    extraction_status: "indexed",
    review_state: "ready",
  },
  {
    id: 2,
    title: "False-Negative Nodal Staging After Systematic Endobronchial Ultrasound",
    authors: "Daniel Brooks, Sofia Almeida",
    journal: "Thoracic Oncology",
    publication_year: 2023,
    source_type: "retrospective_study",
    reading_status: "unread",
    importance: 3,
    page_count: 9,
    why_saved: "Useful missed-metastasis estimate for staging discussions.",
    extraction_status: "indexed",
    review_state: "possible_duplicate",
  },
  {
    id: 3,
    title: "Patient-Centered Outcomes in Pleural Infection Trials",
    authors: "Nadia Okafor et al.",
    journal: "Respiratory Medicine",
    publication_year: 2022,
    source_type: "systematic_review",
    reading_status: "reference",
    importance: 5,
    page_count: 18,
    why_saved: "Shows why radiographic endpoints can diverge from patient experience.",
    extraction_status: "indexed",
    review_state: "ready",
  },
];

const status: CoreStatus = {
  status: "ok",
  version: "0.2.0-browser-test",
  schema_version: 8,
  documents: articles.length,
  review_needed: 1,
  jobs_running: 1,
  embedding_backend: "fastembed:BAAI/bge-small-en-v1.5:q-onnx",
  embedding_warning: null,
  ocr_available: true,
  network_metadata_enabled: false,
  diagnostics_enabled: false,
  taxonomy_profile_enabled: true,
  taxonomy_suggestions_enabled: false,
  taxonomy_auto_apply_enabled: false,
  taxonomy_disease_state_extraction_enabled: false,
};

const jobs: ImportJob[] = [
  {
    id: "2acb3006-a68e-47fd-927c-a20ff3c91bef",
    type: "import",
    source: "Pulmonary papers",
    stage: "extracting_layout",
    status: "running",
    progress_current: 37,
    progress_total: 84,
    progress: 37 / 84,
    retryable: true,
    error_code: null,
    issue_count: 2,
    created_at: now,
    updated_at: now,
  },
];

const projects: Project[] = [
  {
    id: 1,
    name: "Navigation outcomes",
    description: "Papers for a methods and endpoint review.",
    project_type: "collection",
    central_question: "",
    created_at: now,
    updated_at: now,
    article_count: 2,
  },
];

const taxonomyNodes: TaxonomyNode[] = [
  {
    id: "specialty.internal_medicine",
    node_type: "specialty",
    canonical_name: "Internal Medicine",
    status: "active",
    description: "",
    source_system: "ABMS",
    source_code: "Internal Medicine",
    source_version: "taxonomy-v1",
    external_mappings: [],
    metadata: { curation_status: "verified_snapshot" },
  },
  {
    id: "subspecialty.pulmonary_disease",
    node_type: "subspecialty",
    canonical_name: "Pulmonary Disease",
    status: "active",
    description: "",
    source_system: "ABMS",
    source_code: "Pulmonary Disease",
    source_version: "taxonomy-v1",
    external_mappings: [],
    metadata: { curation_status: "verified_snapshot" },
  },
];

const taxonomyPacks: SpecialtyPackSummary[] = [
  {
    pack_id: "pack.subspecialty.pulmonary_disease",
    display_name: "Pulmonary Disease",
    pack_type: "subspecialty",
    version: "1.0.0",
    selection_node_id: "subspecialty.pulmonary_disease",
    curation_status: "curated",
    inherits: ["pack.specialty.internal_medicine"],
    membership_count: 11,
    state_archetypes: ["state_archetype.pulmonary"],
  },
];

const taxonomyTree: PersonalizedTaxonomyTree = {
  catalog_version: "taxonomy-v1",
  profile_revision: "browser-test-profile",
  warnings: [],
  roots: [],
  total_canonical_nodes: 0,
};

let pdfUrl = "";

function browserTestPdfUrl(): string {
  if (pdfUrl) return pdfUrl;
  const pageOne =
    "BT /F1 22 Tf 72 720 Td (Robotic Bronchoscopy Outcomes) Tj 0 -36 Td /F1 12 Tf (Prospective multicenter evaluation of peripheral lesions.) Tj ET";
  const pageTwo =
    "BT /F1 18 Tf 72 720 Td (Results) Tj 0 -32 Td /F1 12 Tf (Navigation success was 94 percent.) Tj 0 -22 Td (Strict diagnostic yield was 71 percent.) Tj ET";
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 7 0 R >> >> /Contents 5 0 R >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 7 0 R >> >> /Contents 6 0 R >>",
    `<< /Length ${pageOne.length} >>\nstream\n${pageOne}\nendstream`,
    `<< /Length ${pageTwo.length} >>\nstream\n${pageTwo}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let document = "%PDF-1.4\n";
  const offsets = [0];
  objects.forEach((object, index) => {
    offsets.push(new TextEncoder().encode(document).length);
    document += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xref = new TextEncoder().encode(document).length;
  document += `xref\n0 ${objects.length + 1}\n`;
  document += "0000000000 65535 f \n";
  document += offsets
    .slice(1)
    .map((offset) => `${offset.toString().padStart(10, "0")} 00000 n \n`)
    .join("");
  document += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  pdfUrl = URL.createObjectURL(
    new Blob([new TextEncoder().encode(document)], { type: "application/pdf" }),
  );
  return pdfUrl;
}

function detail(article: ArticleSummary): ArticleDetail {
  const articleId = Number(article.id);
  return {
    ...article,
    doi: "",
    pmid: "",
    abstract: "",
    user_summary: "",
    metadata_conflicts: [],
    assets: [
      {
        id: articleId + 100,
        article_id: articleId,
        sha256: "a".repeat(64),
        file_name: `${article.id}-browser-test.pdf`,
        role: "article",
        version_label: "managed copy",
        source_kind: "browser_test",
        availability: "available",
        is_primary: true,
        size_bytes: 2_048,
      },
      ...(articleId === 1
        ? [{
            id: articleId + 200,
            article_id: articleId,
            sha256: "b".repeat(64),
            file_name: "publisher-version-browser-test.pdf",
            role: "article",
            version_label: "v2",
            source_kind: "zotero",
            availability: "available",
            is_primary: false,
            size_bytes: 2_048,
          }]
        : []),
    ],
    annotations:
      article.id === 1
        ? [
            {
              id: "17c84e58-a3a9-4bcc-8895-f2670ead56d3",
              article_id: article.id,
              asset_id: article.id + 100,
              page_number: 2,
              annotation_type: "highlight",
              color: "#74B8A7",
              quad_points: [72, 660, 310, 660, 72, 678, 310, 678],
              selected_text: "Strict diagnostic yield was 71 percent.",
              context_hash: "browser-test",
              comment: "Important endpoint definition",
              created_at: now,
              updated_at: now,
            },
          ]
        : [],
  };
}

function searchHits(): SearchHit[] {
  return articles.slice(0, 2).map((article, index) => ({
    rank: index + 1,
    article_id: article.id,
    asset_id: null,
    title: article.title,
    authors: article.authors,
    journal: article.journal,
    publication_year: article.publication_year,
    source_type: article.source_type,
    page_number: index + 2,
    passage_id: index + 10,
    snippet:
      index === 0
        ? "Navigation success was 94%, while strict diagnostic yield was 71%."
        : "Occult nodal metastasis was identified in approximately five percent of cases.",
    bounding_boxes:
      index === 0
        ? [
            {
              x0: 72,
              y0: 655,
              x1: 330,
              y1: 704,
              coordinate_space: "pdf_points",
            },
          ]
        : [],
    match_reasons: [
      { code: "lexical", label: "remembered wording" },
      { code: "numeric", label: "nearby numbers" },
    ],
    why_saved: article.why_saved,
  }));
}

export async function invokeBrowserTest<T>(
  command: string,
  args: Record<string, unknown> | undefined,
): Promise<T> {
  let value: unknown;
  switch (command) {
    case "core_status":
      value = status;
      break;
    case "taxonomy_catalog": {
      const offset = Number(args?.offset ?? 0);
      const limit = Number(args?.limit ?? 100);
      const query = String(args?.query ?? "").toLowerCase();
      const filtered = taxonomyNodes.filter(
        (node) =>
          (!query || node.canonical_name.toLowerCase().includes(query)) &&
          (!args?.nodeType || node.node_type === args.nodeType),
      );
      value = {
        items: filtered.slice(offset, offset + limit).map((node) => ({
          id: node.id,
          node_type: node.node_type,
          canonical_name: node.canonical_name,
          status: node.status,
        })),
        total: filtered.length,
        limit,
        offset,
        catalog_version: "taxonomy-v1",
      } satisfies TaxonomyCatalogPage;
      break;
    }
    case "taxonomy_node":
      value =
        taxonomyNodes.find((node) => node.id === args?.nodeId) ??
        taxonomyNodes[0];
      break;
    case "taxonomy_packs":
      value = taxonomyPacks.filter(
        (pack) => !args?.packType || pack.pack_type === args.packType,
      );
      break;
    case "taxonomy_tree":
      value = taxonomyTree;
      break;
    case "list_articles": {
      const offset = Number(args?.offset ?? 0);
      const limit = Number(args?.limit ?? 100);
      const query = String(args?.query ?? "").toLowerCase();
      const filtered = articles.filter(
        (article) =>
          !query ||
          article.title.toLowerCase().includes(query) ||
          article.authors.toLowerCase().includes(query),
      );
      value = {
        items: filtered.slice(offset, offset + limit),
        total: filtered.length,
        limit,
        offset,
      } satisfies ArticlePage;
      break;
    }
    case "get_article":
      value = detail(
        articles.find((article) => article.id === Number(args?.articleId)) ?? articles[0]!,
      );
      break;
    case "recall_search":
      value = searchHits();
      break;
    case "list_jobs":
      value = jobs;
      break;
    case "list_job_issues":
      value = [
        {
          id: 1,
          job_id: jobs[0]!.id,
          source_label: "encrypted-scan.pdf",
          error_code: "password_required",
          retryable: true,
          created_at: now,
        },
        {
          id: 2,
          job_id: jobs[0]!.id,
          source_label: "damaged-appendix.pdf",
          error_code: "malformed_pdf",
          retryable: false,
          created_at: now,
        },
      ];
      break;
    case "list_projects":
      value = projects;
      break;
    case "list_project_articles":
      value = articles.slice(0, 2);
      break;
    case "list_trash":
      value = [
        {
          id: 9,
          title: "Archived pilot feasibility report",
          deleted_at: now,
          purge_after: new Date(Date.now() + 29 * 86_400_000).toISOString(),
        },
      ] satisfies TrashArticle[];
      break;
    case "asset_url":
      value = browserTestPdfUrl();
      break;
    case "update_privacy":
      value = {
        enable_network_metadata: Boolean(args?.enableNetworkMetadata),
        diagnostics_enabled: Boolean(args?.diagnosticsEnabled),
      };
      break;
    case "check_for_updates":
      value = { available: false, version: null };
      break;
    case "choose_import_folder":
    case "create_backup":
    case "restore_backup":
    case "create_support_bundle":
    case "export_article":
      value = null;
      break;
    case "choose_import_files":
      value = [];
      break;
    case "import_zotero":
    case "retry_job":
    case "install_model":
      value = jobs[0];
      break;
    case "create_project":
      value = { ...projects[0], name: String(args?.name ?? "New project") };
      break;
    case "update_article":
    case "resolve_article_review":
      value = detail(articles[0]!);
      break;
    case "trash_article":
      value = true;
      break;
    case "restore_article":
    case "cancel_job":
    case "delete_annotation":
    case "add_project_article":
      value = undefined;
      break;
    case "add_project_articles": {
      const articleIds = Array.isArray(args?.articleIds)
        ? [...new Set(args.articleIds.map(Number))]
        : [];
      value = {
        project_id: Number(args?.projectId),
        requested: articleIds.length,
        added: articleIds.length,
        already_present: 0,
      };
      break;
    }
    default:
      throw new Error(`Browser test core does not implement ${command}`);
  }
  return value as T;
}
