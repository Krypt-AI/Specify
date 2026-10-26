import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { useCurrentUser } from '@/api/account'
import { AppLayout } from '@/components/layout/AppLayout'
import { UPCOMING_ITEMS } from '@/components/layout/navigation'
import { GROUP_LIST } from '@/lib/groups'
import { ActivityPage } from '@/pages/ActivityPage'
import { CompaniesPage } from '@/pages/CompaniesPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { DecisionQueuePage } from '@/pages/DecisionQueuePage'
import { DraftsPage } from '@/pages/DraftsPage'
import { FolderPage } from '@/pages/FolderPage'
import { FollowUpsPage } from '@/pages/FollowUpsPage'
import { InboxPage } from '@/pages/InboxPage'
import { LoginPage } from '@/pages/LoginPage'
import { OpportunitiesPage } from '@/pages/OpportunitiesPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { SetupWizardPage } from '@/pages/SetupWizardPage'
import { UpcomingPage } from '@/pages/UpcomingPage'
import { WorkflowsPage } from '@/pages/WorkflowsPage'

const AnalyticsPage = lazy(() => import('@/pages/AnalyticsPage').then((m) => ({ default: m.AnalyticsPage })))
const WorkflowBuilderPage = lazy(() => import('@/pages/WorkflowBuilderPage').then((m) => ({ default: m.WorkflowBuilderPage })))

export function App() {
  const { data: user, isLoading, isError } = useCurrentUser()

  if (isLoading) {
    return <p className="p-8 text-sm text-muted">Loading…</p>
  }
  if (isError) {
    return <p className="p-8 text-sm text-danger">Cannot reach the Specify server. Is the backend running?</p>
  }
  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    )
  }
  if (!user.setup_completed) {
    return <SetupWizardPage user={user} />
  }

  return (
    <Routes>
      <Route element={<AppLayout user={user} />}>
        <Route index element={<DashboardPage user={user} />} />
        <Route path="inbox" element={<InboxPage />} />
        {GROUP_LIST.map((group) => (
          <Route key={group.key} path={group.path.slice(1)} element={<FolderPage group={group} />} />
        ))}
        <Route path="decisions" element={<DecisionQueuePage />} />
        <Route path="opportunities" element={<OpportunitiesPage />} />
        <Route path="companies" element={<CompaniesPage />} />
        <Route path="drafts" element={<DraftsPage />} />
        <Route path="workflows" element={<WorkflowsPage />} />
        <Route
          path="workflows/:id"
          element={
            <Suspense fallback={<p className="text-sm text-muted">Loading builder…</p>}>
              <WorkflowBuilderPage />
            </Suspense>
          }
        />
        <Route path="activity" element={<ActivityPage />} />
        <Route path="follow-ups" element={<FollowUpsPage />} />
        <Route
          path="analytics"
          element={
            <Suspense fallback={<p className="text-sm text-muted">Loading analytics…</p>}>
              <AnalyticsPage />
            </Suspense>
          }
        />
        <Route path="settings" element={<SettingsPage user={user} />} />
        {UPCOMING_ITEMS.map((item) => (
          <Route key={item.path} path={item.path.slice(1)} element={<UpcomingPage item={item} />} />
        ))}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
