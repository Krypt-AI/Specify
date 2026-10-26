import { useSearchParams } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { oauthStartUrl } from '@/lib/api'

const ERROR_MESSAGES: Record<string, string> = {
  access_denied: 'Sign-in was cancelled.',
  oauth_failed: 'Google sign-in failed. Please try again.',
}

export function LoginPage() {
  const [params] = useSearchParams()
  const error = params.get('error')

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-sm p-8 text-center">
        <h1 className="text-2xl font-semibold">Specify</h1>
        <p className="mt-2 text-sm text-muted">
          Sorts your recruitment, university and certification email, and drafts replies for you to review.
        </p>
        {error && (
          <p role="alert" className="mt-4 text-sm text-danger">
            {ERROR_MESSAGES[error] ?? ERROR_MESSAGES.oauth_failed}
          </p>
        )}
        <Button className="mt-6 w-full" onClick={() => window.location.assign(oauthStartUrl('login'))}>
          Sign in with Google
        </Button>
        <p className="mt-4 text-xs text-muted">
          Signing in only shares your name and email address. Gmail and Sheets access are requested separately.
        </p>
      </Card>
    </div>
  )
}
