export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  public: {
    Tables: {
      annotations: {
        Row: {
          annotation_type: string
          article_id: string
          asset_id: string
          color: string
          comment: string
          context_hash: string
          created_at: string
          deleted_at: string | null
          id: string
          library_id: string
          owner_id: string
          page_number: number
          quad_points: Json
          revision: number
          selected_text: string
          updated_at: string
        }
        Insert: {
          annotation_type: string
          article_id: string
          asset_id: string
          color?: string
          comment?: string
          context_hash?: string
          created_at?: string
          deleted_at?: string | null
          id?: string
          library_id: string
          owner_id: string
          page_number: number
          quad_points?: Json
          revision?: number
          selected_text?: string
          updated_at?: string
        }
        Update: {
          annotation_type?: string
          article_id?: string
          asset_id?: string
          color?: string
          comment?: string
          context_hash?: string
          created_at?: string
          deleted_at?: string | null
          id?: string
          library_id?: string
          owner_id?: string
          page_number?: number
          quad_points?: Json
          revision?: number
          selected_text?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "annotations_article_id_library_id_owner_id_fkey"
            columns: ["article_id", "library_id", "owner_id"]
            isOneToOne: false
            referencedRelation: "articles"
            referencedColumns: ["id", "library_id", "owner_id"]
          },
          {
            foreignKeyName: "annotations_asset_id_article_id_library_id_owner_id_fkey"
            columns: ["asset_id", "article_id", "library_id", "owner_id"]
            isOneToOne: false
            referencedRelation: "article_assets"
            referencedColumns: ["id", "article_id", "library_id", "owner_id"]
          },
        ]
      }
      article_assets: {
        Row: {
          article_id: string
          availability: string
          created_at: string
          file_name: string
          id: string
          is_primary: boolean
          library_id: string
          mime_type: string
          owner_id: string
          revision: number
          role: string
          sha256: string
          size_bytes: number
          source_connection_id: string | null
          source_kind: string
          source_remote_file_id: string | null
          source_remote_parent_id: string | null
          source_remote_path: string | null
          source_remote_revision: string | null
          storage_bucket: string
          storage_path: string
          updated_at: string
          version_label: string
        }
        Insert: {
          article_id: string
          availability?: string
          created_at?: string
          file_name: string
          id?: string
          is_primary?: boolean
          library_id: string
          mime_type?: string
          owner_id: string
          revision?: number
          role?: string
          sha256: string
          size_bytes: number
          source_connection_id?: string | null
          source_kind?: string
          source_remote_file_id?: string | null
          source_remote_parent_id?: string | null
          source_remote_path?: string | null
          source_remote_revision?: string | null
          storage_bucket?: string
          storage_path: string
          updated_at?: string
          version_label?: string
        }
        Update: {
          article_id?: string
          availability?: string
          created_at?: string
          file_name?: string
          id?: string
          is_primary?: boolean
          library_id?: string
          mime_type?: string
          owner_id?: string
          revision?: number
          role?: string
          sha256?: string
          size_bytes?: number
          source_connection_id?: string | null
          source_kind?: string
          source_remote_file_id?: string | null
          source_remote_parent_id?: string | null
          source_remote_path?: string | null
          source_remote_revision?: string | null
          storage_bucket?: string
          storage_path?: string
          updated_at?: string
          version_label?: string
        }
        Relationships: [
          {
            foreignKeyName: "article_assets_article_id_library_id_owner_id_fkey"
            columns: ["article_id", "library_id", "owner_id"]
            isOneToOne: false
            referencedRelation: "articles"
            referencedColumns: ["id", "library_id", "owner_id"]
          },
          {
            foreignKeyName: "article_assets_source_connection_id_library_id_owner_id_fkey"
            columns: ["source_connection_id", "library_id", "owner_id"]
            isOneToOne: false
            referencedRelation: "cloud_connections"
            referencedColumns: ["id", "library_id", "owner_id"]
          },
        ]
      }
      articles: {
        Row: {
          abstract: string
          authors: string
          created_at: string
          deleted_at: string | null
          doi: string
          extraction_status: string
          id: string
          importance: number
          journal: string
          library_id: string
          metadata_status: string
          owner_id: string
          page_count: number
          pmid: string
          publication_year: number | null
          reading_status: string
          review_state: string
          revision: number
          source_type: string
          title: string
          updated_at: string
          user_summary: string
          why_saved: string
        }
        Insert: {
          abstract?: string
          authors?: string
          created_at?: string
          deleted_at?: string | null
          doi?: string
          extraction_status?: string
          id?: string
          importance?: number
          journal?: string
          library_id: string
          metadata_status?: string
          owner_id: string
          page_count?: number
          pmid?: string
          publication_year?: number | null
          reading_status?: string
          review_state?: string
          revision?: number
          source_type?: string
          title: string
          updated_at?: string
          user_summary?: string
          why_saved?: string
        }
        Update: {
          abstract?: string
          authors?: string
          created_at?: string
          deleted_at?: string | null
          doi?: string
          extraction_status?: string
          id?: string
          importance?: number
          journal?: string
          library_id?: string
          metadata_status?: string
          owner_id?: string
          page_count?: number
          pmid?: string
          publication_year?: number | null
          reading_status?: string
          review_state?: string
          revision?: number
          source_type?: string
          title?: string
          updated_at?: string
          user_summary?: string
          why_saved?: string
        }
        Relationships: [
          {
            foreignKeyName: "articles_library_id_owner_id_fkey"
            columns: ["library_id", "owner_id"]
            isOneToOne: false
            referencedRelation: "libraries"
            referencedColumns: ["id", "owner_id"]
          },
        ]
      }
      backup_replications: {
        Row: {
          article_id: string
          asset_id: string
          attempt_count: number
          created_at: string
          error_code: string | null
          error_message: string
          finished_at: string | null
          id: string
          library_id: string
          owner_id: string
          provider_file_id: string
          provider_path: string
          retryable: boolean
          revision: number
          source_kind: string
          source_sha256: string
          started_at: string | null
          status: string
          target_id: string
          updated_at: string
        }
        Insert: {
          article_id: string
          asset_id: string
          attempt_count?: number
          created_at?: string
          error_code?: string | null
          error_message?: string
          finished_at?: string | null
          id?: string
          library_id: string
          owner_id: string
          provider_file_id?: string
          provider_path?: string
          retryable?: boolean
          revision?: number
          source_kind: string
          source_sha256: string
          started_at?: string | null
          status?: string
          target_id: string
          updated_at?: string
        }
        Update: {
          article_id?: string
          asset_id?: string
          attempt_count?: number
          created_at?: string
          error_code?: string | null
          error_message?: string
          finished_at?: string | null
          id?: string
          library_id?: string
          owner_id?: string
          provider_file_id?: string
          provider_path?: string
          retryable?: boolean
          revision?: number
          source_kind?: string
          source_sha256?: string
          started_at?: string | null
          status?: string
          target_id?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "backup_replications_asset_id_article_id_library_id_owner_i_fkey"
            columns: ["asset_id", "article_id", "library_id", "owner_id"]
            isOneToOne: false
            referencedRelation: "article_assets"
            referencedColumns: ["id", "article_id", "library_id", "owner_id"]
          },
          {
            foreignKeyName: "backup_replications_target_id_library_id_owner_id_fkey"
            columns: ["target_id", "library_id", "owner_id"]
            isOneToOne: false
            referencedRelation: "backup_targets"
            referencedColumns: ["id", "library_id", "owner_id"]
          },
        ]
      }
      backup_targets: {
        Row: {
          conflict_strategy: string
          connection_id: string | null
          copy_cloud_imports: boolean
          copy_device_imports: boolean
          created_at: string
          enabled: boolean
          id: string
          last_error_code: string | null
          last_verified_at: string | null
          library_id: string
          naming_strategy: string
          owner_id: string
          remote_drive_id: string
          remote_folder_id: string
          remote_folder_name: string
          remote_folder_path: string
          revision: number
          updated_at: string
        }
        Insert: {
          conflict_strategy?: string
          connection_id?: string | null
          copy_cloud_imports?: boolean
          copy_device_imports?: boolean
          created_at?: string
          enabled?: boolean
          id?: string
          last_error_code?: string | null
          last_verified_at?: string | null
          library_id: string
          naming_strategy?: string
          owner_id: string
          remote_drive_id?: string
          remote_folder_id?: string
          remote_folder_name?: string
          remote_folder_path?: string
          revision?: number
          updated_at?: string
        }
        Update: {
          conflict_strategy?: string
          connection_id?: string | null
          copy_cloud_imports?: boolean
          copy_device_imports?: boolean
          created_at?: string
          enabled?: boolean
          id?: string
          last_error_code?: string | null
          last_verified_at?: string | null
          library_id?: string
          naming_strategy?: string
          owner_id?: string
          remote_drive_id?: string
          remote_folder_id?: string
          remote_folder_name?: string
          remote_folder_path?: string
          revision?: number
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "backup_targets_connection_id_library_id_owner_id_fkey"
            columns: ["connection_id", "library_id", "owner_id"]
            isOneToOne: false
            referencedRelation: "cloud_connections"
            referencedColumns: ["id", "library_id", "owner_id"]
          },
          {
            foreignKeyName: "backup_targets_library_id_owner_id_fkey"
            columns: ["library_id", "owner_id"]
            isOneToOne: false
            referencedRelation: "libraries"
            referencedColumns: ["id", "owner_id"]
          },
        ]
      }
      cloud_connections: {
        Row: {
          account_email: string
          account_label: string
          created_at: string
          id: string
          last_checked_at: string | null
          last_error_code: string | null
          library_id: string
          owner_id: string
          provider: string
          revision: number
          scopes: string[]
          status: string
          updated_at: string
        }
        Insert: {
          account_email?: string
          account_label?: string
          created_at?: string
          id?: string
          last_checked_at?: string | null
          last_error_code?: string | null
          library_id: string
          owner_id: string
          provider: string
          revision?: number
          scopes?: string[]
          status?: string
          updated_at?: string
        }
        Update: {
          account_email?: string
          account_label?: string
          created_at?: string
          id?: string
          last_checked_at?: string | null
          last_error_code?: string | null
          library_id?: string
          owner_id?: string
          provider?: string
          revision?: number
          scopes?: string[]
          status?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "cloud_connections_library_id_owner_id_fkey"
            columns: ["library_id", "owner_id"]
            isOneToOne: false
            referencedRelation: "libraries"
            referencedColumns: ["id", "owner_id"]
          },
        ]
      }
      jobs: {
        Row: {
          created_at: string
          error_code: string | null
          finished_at: string | null
          id: string
          input: Json
          issue_count: number
          library_id: string
          output: Json
          owner_id: string
          progress_current: number
          progress_total: number
          retryable: boolean
          revision: number
          source: string
          stage: string
          status: string
          type: string
          updated_at: string
        }
        Insert: {
          created_at?: string
          error_code?: string | null
          finished_at?: string | null
          id?: string
          input?: Json
          issue_count?: number
          library_id: string
          output?: Json
          owner_id: string
          progress_current?: number
          progress_total?: number
          retryable?: boolean
          revision?: number
          source?: string
          stage?: string
          status?: string
          type?: string
          updated_at?: string
        }
        Update: {
          created_at?: string
          error_code?: string | null
          finished_at?: string | null
          id?: string
          input?: Json
          issue_count?: number
          library_id?: string
          output?: Json
          owner_id?: string
          progress_current?: number
          progress_total?: number
          retryable?: boolean
          revision?: number
          source?: string
          stage?: string
          status?: string
          type?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "jobs_library_id_owner_id_fkey"
            columns: ["library_id", "owner_id"]
            isOneToOne: false
            referencedRelation: "libraries"
            referencedColumns: ["id", "owner_id"]
          },
        ]
      }
      libraries: {
        Row: {
          created_at: string
          deleted_at: string | null
          id: string
          name: string
          owner_id: string
          revision: number
          sync_mode: string
          updated_at: string
        }
        Insert: {
          created_at?: string
          deleted_at?: string | null
          id?: string
          name?: string
          owner_id: string
          revision?: number
          sync_mode?: string
          updated_at?: string
        }
        Update: {
          created_at?: string
          deleted_at?: string | null
          id?: string
          name?: string
          owner_id?: string
          revision?: number
          sync_mode?: string
          updated_at?: string
        }
        Relationships: []
      }
      project_articles: {
        Row: {
          added_at: string
          article_id: string
          library_id: string
          owner_id: string
          project_id: string
          status: string
        }
        Insert: {
          added_at?: string
          article_id: string
          library_id: string
          owner_id: string
          project_id: string
          status?: string
        }
        Update: {
          added_at?: string
          article_id?: string
          library_id?: string
          owner_id?: string
          project_id?: string
          status?: string
        }
        Relationships: [
          {
            foreignKeyName: "project_articles_article_id_library_id_owner_id_fkey"
            columns: ["article_id", "library_id", "owner_id"]
            isOneToOne: false
            referencedRelation: "articles"
            referencedColumns: ["id", "library_id", "owner_id"]
          },
          {
            foreignKeyName: "project_articles_project_id_library_id_owner_id_fkey"
            columns: ["project_id", "library_id", "owner_id"]
            isOneToOne: false
            referencedRelation: "projects"
            referencedColumns: ["id", "library_id", "owner_id"]
          },
        ]
      }
      projects: {
        Row: {
          central_question: string
          created_at: string
          deleted_at: string | null
          description: string
          id: string
          library_id: string
          name: string
          owner_id: string
          project_type: string
          revision: number
          updated_at: string
        }
        Insert: {
          central_question?: string
          created_at?: string
          deleted_at?: string | null
          description?: string
          id?: string
          library_id: string
          name: string
          owner_id: string
          project_type?: string
          revision?: number
          updated_at?: string
        }
        Update: {
          central_question?: string
          created_at?: string
          deleted_at?: string | null
          description?: string
          id?: string
          library_id?: string
          name?: string
          owner_id?: string
          project_type?: string
          revision?: number
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "projects_library_id_owner_id_fkey"
            columns: ["library_id", "owner_id"]
            isOneToOne: false
            referencedRelation: "libraries"
            referencedColumns: ["id", "owner_id"]
          },
        ]
      }
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      consume_cloud_oauth_state: {
        Args: { p_state_hash: string }
        Returns: {
          encrypted_pkce_verifier: string
          library_id: string
          owner_id: string
          provider: string
          return_to: string
        }[]
      }
      create_cloud_oauth_state: {
        Args: {
          p_encrypted_pkce_verifier: string
          p_expires_at: string
          p_library_id: string
          p_owner_id: string
          p_provider: string
          p_return_to: string
          p_state_hash: string
        }
        Returns: undefined
      }
      queue_library_backups: { Args: { p_asset_id?: string }; Returns: number }
      read_cloud_connection_secret: {
        Args: { p_connection_id: string }
        Returns: {
          encrypted_token_payload: string
          library_id: string
          owner_id: string
          token_expires_at: string
          token_version: number
        }[]
      }
      search_library_chunks: {
        Args: { p_library_id: string; p_limit?: number; p_query: string }
        Returns: {
          article_id: string
          match_rank: number
          page_number: number
          snippet: string
        }[]
      }
      upsert_cloud_connection_secret: {
        Args: {
          p_connection_id: string
          p_encrypted_token_payload: string
          p_library_id: string
          p_owner_id: string
          p_token_expires_at: string
        }
        Returns: undefined
      }
    }
    Enums: {
      [_ in never]: never
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {},
  },
} as const
