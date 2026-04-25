export type Tier = 'NO_RISK' | 'MID_RISK' | 'HIGH_RISK'
export type TransactionStatus =
  | 'APPROVED'
  | 'PENDING_VERIFICATION'
  | 'HELD_FOR_REVIEW'
  | 'FROZEN'
  | 'REJECTED'
export type VerdictKind = 'APPROVED' | 'HELD_FOR_REVIEW' | 'FROZEN'
export type MerchantRep = 'GOOD' | 'BAD' | 'UNKNOWN'

export interface Transaction {
  id: string
  amount_eur: number
  merchant: string
  status: TransactionStatus
  tier: Tier
  merchant_reputation: MerchantRep
  created_at: string
}

export interface User {
  id: string
  name: string
  balance_eur: number
}

export interface InitiateRes {
  transaction_id: string
  tier: Tier
  status: TransactionStatus
  verification_id?: string
  ws_url?: string
  merchant_reputation: MerchantRep
}

export interface HumeScores {
  calmness: number
  fear: number
  distress: number
  anxiety: number
  confidence_overall: number
  verdict_hint: 'CLEAN' | 'AMBIGUOUS' | 'FLAGGED'
  service_available: boolean
  note: string
}

export interface GeminiSummary {
  location_type: string
  duress_signals: string[]
  confidence: number
  raw_text: string
  service_available: boolean
}

export interface VerifyResult {
  verdict: VerdictKind
  rationale: string
  humeScores?: HumeScores
  geminiSummary?: GeminiSummary
}

export type QuestionPurpose =
  | 'baseline'
  | 'intent'
  | 'context'
  | 'knowledge_check'
  | 'stress_probe'

export interface VerificationQuestion {
  id: string
  text: string
  purpose: QuestionPurpose
  expected_answer_shape?: string
}

export interface QuestionTurn {
  id: string
  text: string
  purpose: QuestionPurpose
  status: 'pending' | 'speaking' | 'listening' | 'scoring' | 'done'
  scores?: HumeScores
  delta_vs_baseline?: { fear: number; distress: number; anxiety: number }
}

export interface DemoButton {
  label: string
  scenario: string | null  // null = force NO_RISK, no scenario pin
  merchant: string
  amount: number
  colorClass: string
  subtext: string
  description: string
}
