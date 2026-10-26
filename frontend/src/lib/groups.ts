import { Award, Briefcase, GraduationCap, Mail, type LucideIcon } from 'lucide-react'

import type { MailGroup } from '@/api/types'

export type GroupInfo = {
  key: MailGroup
  label: string
  path: string
  icon: LucideIcon
  description: string
}

// The fixed groups behind the folders. Gmail labels are named by the AI from each email's context.
export const GROUPS: Record<MailGroup, GroupInfo> = {
  recruitment: {
    key: 'recruitment',
    label: 'Recruitment',
    path: '/recruitment',
    icon: Briefcase,
    description: 'Job opportunities, recruiters, applications, interviews and offers.',
  },
  university: {
    key: 'university',
    label: 'University',
    path: '/university',
    icon: GraduationCap,
    description: 'Lecturers, assignments, exams, administration and announcements.',
  },
  certifications: {
    key: 'certifications',
    label: 'Certifications',
    path: '/certifications',
    icon: Award,
    description: 'Exam bookings, results, certificates and renewals.',
  },
  other: {
    key: 'other',
    label: 'Other Emails',
    path: '/other',
    icon: Mail,
    description: 'Personal mail, newsletters and everything else.',
  },
}

export const GROUP_LIST = Object.values(GROUPS)
