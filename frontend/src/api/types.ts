// Mirrors the backend schemas in backend/app/schemas.
export type MailGroup = 'recruitment' | 'university' | 'certifications' | 'other'

export type ProcessingStatus = 'pending' | 'processing' | 'classified' | 'review_required' | 'failed'

export type DraftTone = 'formal' | 'friendly' | 'concise' | 'enthusiastic'

export type CertificationProvider = { name: string; domains: string[] }

export type Preferences = {
  timezone: string | null
  draft_tone: DraftTone
  sync: { initial_sync_days: number; initial_sync_max_messages: number; poll_interval_minutes: number }
  classification: { auto_apply_threshold: number; apply_gmail_labels: boolean; apply_status_labels: boolean }
  university: { domains: string[]; lecturer_emails: string[]; department_emails: string[]; keywords: string[] }
  certifications: { providers: CertificationProvider[] }
  recruitment: {
    job_types: string[]
    locations: string[]
    work_arrangements: ('remote' | 'hybrid' | 'onsite')[]
    min_salary: { amount: number | null; currency: string | null; period: 'year' | 'month' | 'week' | 'day' | 'hour' }
  }
  drafting: {
    length: 'short' | 'medium' | 'long'
    language: string
    profile: { full_name: string; signature: string; phone: string; linkedin_url: string }
  }
  automation: {
    paused: boolean
    update_records: boolean
    generate_drafts: boolean
    approve_before_drafting: boolean
    notify_new_opportunities: boolean
    notify_failures: boolean
  }
  reminders: {
    deadlines: boolean
    exams: boolean
    interviews: boolean
    renewals: boolean
    reply_needed: boolean
    deadline_days_before: number
    exam_days_before: number
    interview_days_before: number
    renewal_days_before: number
    recruiter_follow_up_days: number
  }
  privacy: { email_body_retention_days: number }
}

export type DeepPartial<T> = { [K in keyof T]?: T[K] extends object ? (T[K] extends unknown[] ? T[K] : DeepPartial<T[K]>) : T[K] }

export type User = {
  id: string
  email: string
  name: string
  setup_completed: boolean
  preferences: Preferences
}

export type IntegrationProvider = 'gmail' | 'sheets'

export type IntegrationStatus = {
  provider: IntegrationProvider
  connected: boolean
  connection_status: string
  explanation: string
  scopes: string[]
  last_sync_at: string | null
  error_message: string | null
}

export type LabelRef = { id: string; name: string }

export type LabelSuggestion = { label_id: string | null; name: string; description: string }

export type EmailSummary = {
  id: string
  gmail_thread_url: string
  sender_name: string
  sender_email: string
  subject: string
  snippet: string
  received_at: string
  is_unread: boolean
  primary_group: MailGroup | null
  secondary_groups: MailGroup[]
  label: LabelRef | null
  label_suggestion: LabelSuggestion | null
  confidence: number | null
  processing_status: ProcessingStatus
  is_suspicious: boolean
  reply_required: boolean
  opportunity: OpportunityRef | null
}

export type Attachment = { filename: string; mime_type: string; size: number }

export type EmailDetail = EmailSummary & {
  reply_to: string | null
  recipients: { type: 'to' | 'cc'; name: string; email: string }[]
  body_text: string
  body_truncated: boolean
  body_purged_at: string | null
  attachments: Attachment[]
  classification_source: 'rule' | 'ai' | 'user' | 'fallback' | null
  classification_explanation: string | null
  recommended_action: string | null
  suspicious_reasons: string[]
  extracted_data: { organization?: string; dates?: KeyDate[] }
  processing_error: string | null
  classified_at: string | null
  recruitment_note: string | null
}

export type EmailPage = { items: EmailSummary[]; total: number; page: number; page_size: number }

export type EmailFilters = {
  folder?: MailGroup
  label_id?: string
  status?: ProcessingStatus
  unread?: boolean
  q?: string
  page?: number
  page_size?: number
}

export type EmailStats = {
  total: number
  unread: number
  pending: number
  needs_review: number
  failed: number
  suspicious: number
  by_group: Record<MailGroup, number>
  last_gmail_sync_at: string | null
}

export type ClassificationUpdate = {
  primary_group: MailGroup
  secondary_groups: MailGroup[]
  label_id?: string | null
  new_label_name?: string | null
  is_suspicious?: boolean
}

export type SyncStatus = {
  connected: boolean
  status: 'idle' | 'running' | 'error'
  last_synced_at: string | null
  initial_sync_completed_at: string | null
  last_error: string | null
  queued_emails: number
}

export type Label = {
  id: string
  name: string
  description: string
  created_by: 'ai' | 'user' | 'system'
  enabled: boolean
  system_key: string | null
  last_used_at: string | null
  email_count: number
}

export type RuleConditions = {
  sender_emails: string[]
  sender_domains: string[]
  subject_contains: string[]
  body_contains: string[]
}

export type RuleInput = {
  name: string
  conditions: Partial<RuleConditions>
  target_group: MailGroup
  target_label_id?: string | null
  enabled?: boolean
}

export type Rule = RuleInput & { id: string; conditions: RuleConditions; enabled: boolean; created_at: string }

export type RuleSuggestion = { reason: string; rule: RuleInput }

// Recruitment (backend/app/schemas/recruitment.py)
export type OpportunityStatus =
  | 'new'
  | 'awaiting_decision'
  | 'interested'
  | 'more_info_required'
  | 'preparing_application'
  | 'applied'
  | 'interview_scheduled'
  | 'interview_completed'
  | 'offer_received'
  | 'offer_accepted'
  | 'offer_declined'
  | 'rejected'
  | 'withdrawn'
  | 'archived'

export type DecisionName =
  | 'interested'
  | 'interested_need_info'
  | 'request_salary'
  | 'request_job_description'
  | 'request_interview_details'
  | 'request_more_time'
  | 'decline'
  | 'already_applied'
  | 'save_for_later'
  | 'irrelevant'
  | 'custom'

export type CompanyType = 'employer' | 'agency' | 'unknown'
export type WorkArrangement = 'remote' | 'hybrid' | 'onsite'
export type Priority = 'low' | 'normal' | 'high'

export type OpportunityRef = {
  id: string
  job_title: string
  company_name: string | null
  status: OpportunityStatus
  decision: DecisionName | null
}

export type ContactRef = { id: string; name: string; email: string }

export type OpportunitySummary = {
  id: string
  job_title: string
  company: { id: string; name: string } | null
  recruiter: ContactRef | null
  status: OpportunityStatus
  decision: DecisionName | null
  custom_decision: string | null
  priority: Priority
  salary_min: number | null
  salary_max: number | null
  salary_currency: string | null
  salary_period: string | null
  work_arrangement: WorkArrangement | null
  location: string | null
  application_deadline: string | null
  date_received: string
  last_contact_at: string | null
  next_follow_up_at: string | null
}

export type DuplicateCandidate = {
  id: string
  entity_type: 'company' | 'opportunity'
  record_id: string
  candidate_id: string
  record_name: string
  candidate_name: string
  score: number
  reason: string
  created_at: string
}

export type OpportunityDetail = OpportunitySummary & {
  job_reference: string | null
  job_description: string
  employment_type: string | null
  benefits: string[]
  deadline_text: string | null
  application_source: string
  gmail_thread_url: string | null
  notes: string
  advice: { decision: DecisionName; explanation: string; source: 'ai' | 'rules' } | null
  missing_information: ('salary' | 'job_description' | 'work_arrangement' | 'location')[]
  preference_flags: string[]
  emails: { id: string; subject: string; sender_name: string; sender_email: string; snippet: string; received_at: string; gmail_thread_url: string }[]
  decisions: { id: string; decision: DecisionName; custom_decision: string | null; notes: string; created_at: string }[]
  duplicates: DuplicateCandidate[]
}

export type OpportunityPage = { items: OpportunitySummary[]; total: number; page: number; page_size: number }

export type OpportunityFilters = { status?: OpportunityStatus; queue?: boolean; company_id?: string; q?: string; page?: number }

export type OpportunityFields = Partial<{
  job_title: string
  job_reference: string | null
  job_description: string | null
  employment_type: string | null
  work_arrangement: WorkArrangement | null
  location: string | null
  salary_min: number | null
  salary_max: number | null
  salary_currency: string | null
  salary_period: string | null
  application_deadline: string | null
  priority: Priority
  notes: string
  company_id: string | null
}>

export type OpportunityStats = {
  decision_queue: number
  active: number
  interviews_scheduled: number
  offers_received: number
  pending_duplicates: number
  by_status: Record<string, number>
}

export type Contact = ContactRef & { company_id: string | null; phone: string | null; role: string | null; notes: string }

export type Company = {
  id: string
  name: string
  domain: string | null
  website: string | null
  industry: string | null
  country: string | null
  location: string | null
  company_type: CompanyType
  notes: string
  first_contact_at: string | null
  last_contact_at: string | null
  opportunity_count: number
  contact_count: number
}

export type CompanyDetail = Company & { contacts: Contact[]; opportunities: OpportunitySummary[] }

// Google Sheets (backend/app/schemas/sheets.py)
export type SheetEntity = 'companies' | 'opportunities' | 'applications' | 'activity' | 'emails'

export type WorksheetConfig = {
  enabled: boolean
  title: string
  direction: 'export' | 'two_way'
  source_of_truth: 'database' | 'sheets'
  columns: Record<string, string>
}

export type SheetsSettings = {
  worksheets: Record<SheetEntity, WorksheetConfig>
  email_tracker_groups: MailGroup[]
  auto_sync: boolean
}

export type SyncJob = {
  id: string
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  trigger: string
  attempt_count: number
  last_error: string | null
  summary: Record<string, { created: number; updated: number; imported: number; deleted: number; conflicts: number; notes: string[] }>
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export type SheetsStatus = {
  connected: boolean
  spreadsheet: { id: string; url: string; title: string } | null
  settings: SheetsSettings | null
  fields: Record<SheetEntity, { key: string; header: string; importable: boolean }[]>
  two_way_capable: Record<SheetEntity, boolean>
  open_conflicts: number
  last_job: SyncJob | null
}

export type SheetConflict = {
  id: string
  entity: SheetEntity
  record_id: string
  field: string
  field_label: string
  specify_value: string | null
  sheet_value: string | null
  reason: string
  created_at: string
}

// Drafts (backend/app/schemas/drafts.py)
export type Draft = {
  id: string
  email: { id: string; subject: string; sender_email: string; gmail_thread_url: string; primary_group: MailGroup | null }
  opportunity_id: string | null
  scenario: string
  decision: DecisionName | null
  tone: string
  instructions: string
  recipient: string
  subject: string
  body: string
  generated_by: 'ai' | 'template' | null
  warnings: string[]
  status: 'generating' | 'ready' | 'failed' | 'discarded'
  edited_by_user: boolean
  error: string | null
  gmail_draft_id: string | null
  gmail_message_id: string | null
  gmail_synced_at: string | null
  created_at: string
  updated_at: string
}

export type DraftTemplate = {
  scenario: string
  label: string
  instructions: string
  body: string
  use_ai: boolean
  customized: boolean
}

// Workflows (backend/app/schemas/workflows.py)
export type WorkflowNode = { id: string; type: string; config: Record<string, unknown>; position: { x: number; y: number } }
export type WorkflowEdge = { id: string; source: string; target: string; handle: string }
export type WorkflowGraph = { nodes: WorkflowNode[]; edges: WorkflowEdge[] }

export type ConfigFieldSpec = {
  key: string
  label: string
  kind: 'text' | 'textarea' | 'number' | 'boolean' | 'select' | 'tags'
  default: unknown
  options: string[]
  minimum: number | null
  maximum: number | null
  help: string
}

export type NodeTypeSpec = {
  key: string
  label: string
  category: string
  description: string
  handles: string[]
  fields: ConfigFieldSpec[]
  trigger: boolean
  requires_email: boolean
  retryable: boolean
  defaults: Record<string, unknown>
}

export type RunStatus = 'running' | 'waiting' | 'retrying' | 'paused' | 'completed' | 'failed' | 'cancelled'

export type WorkflowRunSummary = {
  id: string
  workflow_definition_id: string
  workflow_name: string
  trigger_event_id: string
  is_test: boolean
  status: RunStatus
  current_node_id: string | null
  waiting_for: { kind: string; message?: string; opportunity_id?: string; until?: string } | null
  resume_at: string | null
  started_at: string | null
  finished_at: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export type NodeRun = {
  id: string
  node_id: string
  node_type: string
  status: string
  attempt: number
  input_summary: Record<string, unknown>
  output_summary: Record<string, unknown>
  started_at: string | null
  finished_at: string | null
  error_message: string | null
  error_category: string | null
}

export type WorkflowRunDetail = WorkflowRunSummary & {
  definition_snapshot: WorkflowGraph
  node_runs: NodeRun[]
  last_error: { node_id: string; message: string; category: string } | null
}

export type Workflow = {
  id: string
  name: string
  description: string
  definition_json: WorkflowGraph
  trigger_type: string
  enabled: boolean
  is_default: boolean
  is_template: boolean
  version: number
  created_at: string
  updated_at: string
  problems: string[]
  last_run: WorkflowRunSummary | null
  waiting_runs: number
  failed_runs: number
}

export type WorkflowTemplate = { key: string; name: string; description: string; built_in: boolean }

export type ActivityEvent = {
  id: string
  action: string
  entity_type: string | null
  entity_id: string | null
  details: Record<string, unknown>
  created_at: string
}

// Reminders, notifications and analytics
export type FollowUp = {
  id: string
  kind: string
  title: string
  notes: string
  due_at: string
  snoozed_until: string | null
  status: 'open' | 'done' | 'cancelled'
  source: string
  completed_at: string | null
  opportunity_id: string | null
  email_message_id: string | null
  overdue: boolean
  context: string | null
}

export type AppNotification = {
  id: string
  kind: string
  title: string
  body: string
  link: string | null
  read_at: string | null
  created_at: string
}

export type Analytics = {
  days: number
  emails_by_group: Record<MailGroup, number>
  opportunities_by_status: Record<string, number>
  decisions_by_outcome: Record<string, number>
  activity_by_week: { week_start: string; recruitment_emails: number; opportunities_created: number; decisions: number }[]
  follow_ups: { completed: number; open: number; overdue: number }
  workflow_runs: Record<string, number>
}

export type DashboardSummary = {
  follow_ups_due: number
  follow_ups_overdue: number
  drafts_ready: number
  workflows_failed: number
  workflows_waiting: number
}

export type KeyDate = { kind: string; text: string; date: string | null; time: string | null; ambiguous: boolean }
