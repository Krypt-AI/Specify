import { useDisconnectIntegration } from '@/api/account'
import type { IntegrationStatus } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardHeader } from '@/components/ui/card'
import { oauthStartUrl } from '@/lib/api'
import { formatDateTime } from '@/lib/utils'

const PROVIDER_NAMES = { gmail: 'Gmail', sheets: 'Google Sheets' } as const

export function IntegrationCard({ integration }: { integration: IntegrationStatus }) {
  const disconnect = useDisconnectIntegration()
  const name = PROVIDER_NAMES[integration.provider]

  const confirmDisconnect = () => {
    if (window.confirm(`Disconnect ${name}? Specify will revoke its Google access.`)) {
      disconnect.mutate(integration.provider)
    }
  }

  return (
    <Card>
      <CardHeader
        title={name}
        description={integration.explanation}
        action={
          integration.connected ? (
            <Badge tone="success">Connected</Badge>
          ) : integration.connection_status === 'not_connected' ? (
            <Badge>Not connected</Badge>
          ) : (
            <Badge tone="warning">Needs attention</Badge>
          )
        }
      />
      <details className="text-sm">
        <summary className="cursor-pointer text-muted">Permissions requested</summary>
        <ul className="mt-2 space-y-1 font-mono text-xs break-all text-muted">
          {integration.scopes.map((scope) => (
            <li key={scope}>{scope}</li>
          ))}
        </ul>
      </details>
      {integration.error_message && <p className="mt-3 text-sm text-danger">{integration.error_message}</p>}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        {integration.connected ? (
          <Button variant="danger" onClick={confirmDisconnect} disabled={disconnect.isPending}>
            Disconnect
          </Button>
        ) : (
          <Button onClick={() => window.location.assign(oauthStartUrl(integration.provider))}>
            {integration.connection_status === 'not_connected' ? 'Connect' : 'Reconnect'}
          </Button>
        )}
        {integration.connected && (
          <span className="text-xs text-muted">Last sync: {formatDateTime(integration.last_sync_at)}</span>
        )}
      </div>
    </Card>
  )
}
