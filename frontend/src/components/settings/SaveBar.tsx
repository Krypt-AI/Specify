import { Button } from '@/components/ui/button'

type MutationState = { isPending: boolean; isSuccess: boolean; isError: boolean; error: Error | null }

/** Save button with inline success and error feedback for a settings section. */
export function SaveBar({
  mutation,
  onSave,
  label = 'Save',
}: {
  mutation: MutationState
  onSave: () => void
  label?: string
}) {
  return (
    <div className="flex items-center gap-3">
      <Button onClick={onSave} disabled={mutation.isPending}>
        {label}
      </Button>
      {mutation.isSuccess && <span className="text-sm text-success">Saved</span>}
      {mutation.isError && <span className="text-sm text-danger">{mutation.error?.message}</span>}
    </div>
  )
}
