import { useStore } from '@nanostores/react'

import { ModelVisibilityDialog } from '@/components/model-visibility-dialog'
import type { NunmaiGateway } from '@/nunmai'
import { $modelVisibilityOpen, setModelVisibilityOpen } from '@/store/model-visibility'
import { $activeSessionId, $gatewayState } from '@/store/session'

interface ModelVisibilityOverlayProps {
  gateway?: NunmaiGateway
  onOpenProviders: () => void
  profile: string
}

export function ModelVisibilityOverlay({ gateway, onOpenProviders, profile }: ModelVisibilityOverlayProps) {
  const activeSessionId = useStore($activeSessionId)
  const gatewayOpen = useStore($gatewayState) === 'open'
  const open = useStore($modelVisibilityOpen)

  if (!gatewayOpen) {
    return null
  }

  return (
    <ModelVisibilityDialog
      gw={gateway}
      onOpenChange={setModelVisibilityOpen}
      onOpenProviders={onOpenProviders}
      open={open}
      profile={profile}
      sessionId={activeSessionId}
    />
  )
}
