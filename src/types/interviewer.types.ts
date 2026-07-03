export type ProjectType = 'web_app' | 'data_pipeline' | 'api_service' | 'tool_utility' | 'general';

export type InterviewStatus = 'active' | 'completed' | 'cancelled';

export type InterviewMessageRole = 'interviewer' | 'stakeholder' | 'system';

export type RequirementPriority = 'must' | 'should' | 'could';

export type ComplexityLevel = 'low' | 'medium' | 'high';

export interface InterviewQuestion {
  id: string;
  text: string;
  category:
    | 'goals'
    | 'users'
    | 'features'
    | 'constraints'
    | 'tech_stack'
    | 'timeline'
    | 'risks'
    | 'scope'
    | 'integration'
    | 'validation';
  required?: boolean;
  askedAt: number;
  askedByProvider?: string;
  metadata?: Record<string, unknown>;
}

export interface InterviewAnswer {
  questionId: string;
  text: string;
  stakeholderId?: string;
  answeredAt: number;
  confidence: number;
  clarifiesQuestionIds?: string[];
}

export interface InterviewTurn {
  id: string;
  role: InterviewMessageRole;
  content: string;
  timestamp: number;
  question?: InterviewQuestion;
  answer?: InterviewAnswer;
}

export interface ExtractedRequirement {
  id: string;
  title: string;
  description: string;
  priority: RequirementPriority;
  category: InterviewQuestion['category'];
  sourceTurnId: string;
  assumptions: string[];
  acceptanceCriteria: string[];
}

export interface BuildTask {
  id: string;
  title: string;
  description: string;
  priority: RequirementPriority;
  complexity: ComplexityLevel;
  effortHours: number;
  dependencies: string[];
  phase: string;
}

export interface BuildPhase {
  id: string;
  title: string;
  objective: string;
  tasks: BuildTask[];
  risks: string[];
}

export interface BuildPlan {
  id: string;
  sessionId: string;
  version: number;
  createdAt: number;
  updatedAt: number;
  projectType: ProjectType;
  summary: string;
  requirements: ExtractedRequirement[];
  constraints: string[];
  assumptions: string[];
  risks: string[];
  recommendations: string[];
  complexity: ComplexityLevel;
  estimatedEffortHours: number;
  roadmap: BuildPhase[];
  unresolvedQuestions: string[];
}

export interface BuildPlanExport {
  json: BuildPlan;
  markdown: string;
}

export interface InterviewSession {
  id: string;
  status: InterviewStatus;
  projectType: ProjectType;
  title?: string;
  startedAt: number;
  updatedAt: number;
  completedAt?: number;
  primaryStakeholderId?: string;
  stakeholderIds: string[];
  turns: InterviewTurn[];
  extractedRequirements: ExtractedRequirement[];
  answeredQuestionIds: string[];
  pendingQuestionIds: string[];
  askedClarificationCount: number;
  maxQuestions: number;
  complexitySignal: number;
  scopeCreepSignal: number;
  /** Non-fatal degradations (e.g. askProvider failures) surfaced for inspection. */
  providerWarnings?: string[];
  activePlanId?: string;
}

export interface InterviewTemplate {
  projectType: ProjectType;
  name: string;
  description: string;
  baseQuestions: Array<{
    id: string;
    text: string;
    category: InterviewQuestion['category'];
    required?: boolean;
  }>;
}

export interface InterviewMetrics {
  sessionsStarted: number;
  sessionsCompleted: number;
  averageTurnsPerSession: number;
  averageQuestionsPerSession: number;
  averagePlanEffortHours: number;
}

export interface InterviewConfig {
  enabled: boolean;
  requireForComplexBuilds: boolean;
  complexityThreshold: number;
  maxQuestions: number;
  allowBypassForSimpleRequests: boolean;
  allowOverrideByFlag: boolean;
  template: 'auto' | ProjectType;
}

export interface InterviewStartInput {
  sessionId: string;
  projectType?: ProjectType;
  title?: string;
  stakeholderId?: string;
  forceTemplate?: ProjectType;
  maxQuestions?: number;
}

export interface InterviewResponse {
  session: InterviewSession;
  nextQuestion?: InterviewQuestion;
  done: boolean;
  needsClarification?: boolean;
  clarificationPrompt?: string;
  generatedPlan?: BuildPlan;
}

export interface InterviewManagerLike {
  start(input: InterviewStartInput): Promise<InterviewResponse>;
  answer(sessionId: string, answer: string, stakeholderId?: string): Promise<InterviewResponse>;
  getSession(sessionId: string): Promise<InterviewSession | null>;
  getPlan(sessionId: string): Promise<BuildPlan | null>;
  exportPlan(sessionId: string): Promise<BuildPlanExport | null>;
  shouldGateBuild(userMessage: string): Promise<{ gated: boolean; reason?: string }>;
  complete(sessionId: string): Promise<BuildPlan | null>;
  getMetrics(): InterviewMetrics;
}
