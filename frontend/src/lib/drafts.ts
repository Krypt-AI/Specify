export const SCENARIO_LABELS: Record<string, string> = {
  interested: 'Interested',
  interested_need_info: 'Interested, need more information',
  request_salary: 'Request salary details',
  request_job_description: 'Request job description',
  request_interview_details: 'Request interview details',
  request_more_time: 'Request more time',
  decline: 'Decline',
  custom: 'Custom decision',
  university_reply: 'Reply to a university email',
  certification_reply: 'Reply to a certification provider',
  general_reply: 'General reply',
}

export const TONE_OPTIONS = ['formal', 'friendly and professional', 'concise', 'enthusiastic', 'polite decline', 'request for clarification']

/** Opens the draft in Gmail's compose window for the right account. */
export function gmailDraftUrl(accountEmail: string, messageId: string) {
  return `https://mail.google.com/mail/?authuser=${encodeURIComponent(accountEmail)}#drafts?compose=${messageId}`
}
