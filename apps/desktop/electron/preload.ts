import { contextBridge, ipcRenderer, webFrame, webUtils } from 'electron'

// Which translucency the OS can back. Asked synchronously because the renderer
// needs it before its first paint, and answered by main because deciding it
// needs `os.release()` — a sandboxed preload may only require electron, events,
// timers and url, so importing node:os here throws before contextBridge runs
// and takes the ENTIRE bridge down with it (window.nunmaiDesktop undefined =>
// "Desktop IPC bridge is unavailable"). No reply means no glass, which degrades
// to an ordinary opaque window rather than a page thinned over nothing.
const translucencySupport = ipcRenderer.sendSync('nunmai:translucency:support')
const hudWindowing = ipcRenderer.sendSync('nunmai:hud:windowing')
const hudNativeDrag = hudWindowing?.nativeDrag === true

contextBridge.exposeInMainWorld('nunmaiDesktop', {
  glassSupported: translucencySupport?.glass === true,
  translucencySupported: translucencySupport?.translucency === true,
  getConnection: profile => ipcRenderer.invoke('nunmai:connection', profile),
  // Registry-scoped backend resolution: { connectionId, profile } → descriptor.
  getConnectionFor: payload => ipcRenderer.invoke('nunmai:connection:for', payload),
  getProfileRoutes: profiles => ipcRenderer.invoke('nunmai:plugin-profile-routes', profiles),
  revalidateConnection: () => ipcRenderer.invoke('nunmai:connection:revalidate'),
  touchBackend: profile => ipcRenderer.invoke('nunmai:backend:touch', profile),
  getGatewayWsUrl: profile => ipcRenderer.invoke('nunmai:gateway:ws-url', profile),
  // Registry-scoped fresh WS URL: { connectionId, profile } → result shape of
  // getGatewayWsUrl, minted against that connection's backend.
  getGatewayWsUrlFor: payload => ipcRenderer.invoke('nunmai:gateway:ws-url-for', payload),
  // Union agent roster across every registered connection.
  getAgentRoster: () => ipcRenderer.invoke('nunmai:agents:roster'),
  openSessionWindow: (sessionId, opts) => ipcRenderer.invoke('nunmai:window:openSession', sessionId, opts),
  openSessionInTerminal: (sessionId, opts) => ipcRenderer.invoke('nunmai:window:openInTerminal', sessionId, opts),
  openWindow: () => ipcRenderer.invoke('nunmai:window:openInstance'),
  openBrowserWindow: tabId => ipcRenderer.invoke('nunmai:window:openBrowser', tabId),
  onBrowserPopoutClosed: callback => {
    const listener = (_event, tabId) => callback(tabId)
    ipcRenderer.on('nunmai:browser-popout:closed', listener)

    return () => ipcRenderer.removeListener('nunmai:browser-popout:closed', listener)
  },
  claimAmbientCue: key => ipcRenderer.invoke('nunmai:ambient:claim', key),
  wakeIndicator: {
    getState: () => ipcRenderer.invoke('nunmai:wake-indicator:get'),
    setState: state => ipcRenderer.send('nunmai:wake-indicator:set', state),
    onState: callback => {
      const listener = (_event, state) => callback(state)
      ipcRenderer.on('nunmai:wake-indicator:state', listener)

      return () => ipcRenderer.removeListener('nunmai:wake-indicator:state', listener)
    }
  },
  petOverlay: {
    // Main renderer → main process: window lifecycle + drag. `request` is
    // `{ bounds, screen }`; resolves with the screen bounds it actually used.
    open: request => ipcRenderer.invoke('nunmai:pet-overlay:open', request),
    close: () => ipcRenderer.invoke('nunmai:pet-overlay:close'),
    setBounds: bounds => ipcRenderer.send('nunmai:pet-overlay:set-bounds', bounds),
    setIgnoreMouse: ignore => ipcRenderer.send('nunmai:pet-overlay:ignore-mouse', ignore),
    // Flip the overlay focusable (and focus it) while the composer needs keys.
    setFocusable: focusable => ipcRenderer.send('nunmai:pet-overlay:set-focusable', focusable),
    // Main renderer → overlay (forwarded by main): push the latest pet state.
    pushState: payload => ipcRenderer.send('nunmai:pet-overlay:state', payload),
    // Overlay → main renderer (forwarded by main): pop back in / composer submit.
    control: payload => ipcRenderer.send('nunmai:pet-overlay:control', payload),
    // Overlay subscribes to state pushes.
    onState: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('nunmai:pet-overlay:state', listener)

      return () => ipcRenderer.removeListener('nunmai:pet-overlay:state', listener)
    },
    // Main renderer subscribes to overlay control messages.
    onControl: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('nunmai:pet-overlay:control', listener)

      return () => ipcRenderer.removeListener('nunmai:pet-overlay:control', listener)
    }
  },
  // HUD mode: the chrome-free floating chat. A full app renderer (own gateway)
  // sized as a floating bar, so it mounts the real composer. Main owns the
  // window; `onChanged` keeps every window's toggle truthful.
  hud: {
    nativeDrag: hudNativeDrag,
    windowing: {
      clientPlacement: hudWindowing?.clientPlacement !== false,
      controlDrag: hudWindowing?.controlDrag === true,
      nativeDrag: hudNativeDrag,
      solid: hudWindowing?.solid === true,
      workspaceTransfer: hudWindowing?.workspaceTransfer === true
    },
    open: request => ipcRenderer.invoke('nunmai:hud:open', request),
    close: () => ipcRenderer.invoke('nunmai:hud:close'),
    setIgnoreMouse: ignore => ipcRenderer.send('nunmai:hud:ignore-mouse', ignore),
    beginMove: () => ipcRenderer.send('nunmai:hud:begin-move'),
    endMove: () => ipcRenderer.send('nunmai:hud:end-move'),
    moveBy: delta => ipcRenderer.send('nunmai:hud:move-by', delta),
    setWorkspaceTransfer: transferring => ipcRenderer.send('nunmai:hud:workspace-transfer', transferring),
    setBounds: bounds => ipcRenderer.send('nunmai:hud:set-bounds', bounds),
    resetLayout: () => ipcRenderer.invoke('nunmai:hud:reset-layout'),
    // Whether the band covers the window below the bar. Main pairs it with the
    // user's translucency setting to decide the native frost (macOS vibrancy /
    // Windows 11 DWM backdrop) — see hudFrostFor.
    setFrost: showing => ipcRenderer.invoke('nunmai:hud:frost', showing),
    // The HUD tells main which session it is on; main hands that back to the
    // app window when the HUD closes, so the app can re-home onto it.
    setSession: sessionId => ipcRenderer.send('nunmai:hud:session', sessionId),
    onGoto: callback => {
      const listener = (_event, sessionId) => callback(sessionId)
      ipcRenderer.on('nunmai:hud:goto', listener)

      return () => ipcRenderer.removeListener('nunmai:hud:goto', listener)
    },
    onChanged: callback => {
      const listener = (_event, state) => callback(state)
      ipcRenderer.on('nunmai:hud:changed', listener)

      return () => ipcRenderer.removeListener('nunmai:hud:changed', listener)
    },
    // Linux only, and silent elsewhere: where the cursor is, in page
    // coordinates, or null when it has left the window. Stands in for the
    // mousemove that `setIgnoreMouseEvents(true, { forward: true })` delivers on
    // macOS and Windows but not here.
    onCursor: callback => {
      const listener = (_event, point) => callback(point)
      ipcRenderer.on('nunmai:hud:cursor', listener)

      return () => ipcRenderer.removeListener('nunmai:hud:cursor', listener)
    },
    // Main's game-overlay watch: whether a fullscreen app (a game) is under
    // the HUD, so the renderer can step back to the low-opacity overlay
    // treatment while one owns the screen.
    onGameOverlay: callback => {
      const listener = (_event, state) => callback(state)
      ipcRenderer.on('nunmai:hud:game-overlay', listener)

      return () => ipcRenderer.removeListener('nunmai:hud:game-overlay', listener)
    }
  },
  // Quick Entry: the global-hotkey mini composer window. Main owns the OS
  // shortcut + the persisted preference; the quick window only captures text
  // and hands it back, and the primary renderer submits it through the normal
  // prompt path.
  quickEntry: {
    getSettings: () => ipcRenderer.invoke('nunmai:quick-entry:settings:get'),
    setSettings: patch => ipcRenderer.invoke('nunmai:quick-entry:settings:set', patch),
    submit: payload => ipcRenderer.send('nunmai:quick-entry:submit', payload),
    dismiss: () => ipcRenderer.send('nunmai:quick-entry:dismiss'),
    // Primary renderer → main → quick window: gateway connection state + the
    // recent-session options the target picker offers. Main caches the latest
    // payload so a freshly spawned quick window starts from truth.
    pushState: payload => ipcRenderer.send('nunmai:quick-entry:state', payload),
    // Quick window subscribes to those pushes.
    onState: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('nunmai:quick-entry:state', listener)

      return () => ipcRenderer.removeListener('nunmai:quick-entry:state', listener)
    },
    // Main → primary renderer: a submit captured by the quick window.
    onSubmit: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('nunmai:quick-entry:submit', listener)

      return () => ipcRenderer.removeListener('nunmai:quick-entry:submit', listener)
    },
    // Main → quick window: you were just summoned (reset draft + refocus).
    onShown: callback => {
      const listener = () => callback()
      ipcRenderer.on('nunmai:quick-entry:shown', listener)

      return () => ipcRenderer.removeListener('nunmai:quick-entry:shown', listener)
    }
  },
  getBootProgress: () => ipcRenderer.invoke('nunmai:boot-progress:get'),
  getConnectionConfig: profile => ipcRenderer.invoke('nunmai:connection-config:get', profile),
  saveConnectionConfig: payload => ipcRenderer.invoke('nunmai:connection-config:save', payload),
  applyConnectionConfig: payload => ipcRenderer.invoke('nunmai:connection-config:apply', payload),
  testConnectionConfig: payload => ipcRenderer.invoke('nunmai:connection-config:test', payload),
  // Opt-in OS-keychain encryption for stored gateway secrets (default off —
  // see secret-storage-policy.ts). get never touches the OS keychain.
  getSecretStorageEncryption: () => ipcRenderer.invoke('nunmai:secret-storage:get'),
  setSecretStorageEncryption: (on: boolean) => ipcRenderer.invoke('nunmai:secret-storage:set', on),
  // v2 multi-connection registry: named agent sources (local / remote / cloud / ssh).
  connections: {
    list: () => ipcRenderer.invoke('nunmai:connections:list'),
    save: payload => ipcRenderer.invoke('nunmai:connections:save', payload),
    remove: id => ipcRenderer.invoke('nunmai:connections:remove', id),
    setPrimary: id => ipcRenderer.invoke('nunmai:connections:set-primary', id),
    setLaunchMode: mode => ipcRenderer.invoke('nunmai:connections:set-launch-mode', mode),
    setLastUsed: id => ipcRenderer.invoke('nunmai:connections:set-last-used', id),
    test: id => ipcRenderer.invoke('nunmai:connections:test', id),
    updateManaged: id => ipcRenderer.invoke('nunmai:connections:update-managed', id),
    // Fan out `nunmai update` to every eligible registered connection.
    // Optional excludeIds skips rows the caller updates through another path.
    updateAll: options => ipcRenderer.invoke('nunmai:connections:update-all', options),
    // Registry lifecycle push (main → renderer): a connection was removed or
    // materially edited, so secondaries scoped to it must be disposed (and,
    // for edits, re-dialed at the new target).
    onChanged: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('nunmai:connections:changed', listener)

      return () => ipcRenderer.removeListener('nunmai:connections:changed', listener)
    }
  },
  sshConfigHosts: () => ipcRenderer.invoke('nunmai:ssh-config:hosts'),
  sshResolveHost: host => ipcRenderer.invoke('nunmai:ssh-config:resolve', host),
  probeConnectionConfig: remoteUrl => ipcRenderer.invoke('nunmai:connection-config:probe', remoteUrl),
  oauthLoginConnectionConfig: remoteUrl => ipcRenderer.invoke('nunmai:connection-config:oauth-login', remoteUrl),
  oauthLogoutConnectionConfig: remoteUrl => ipcRenderer.invoke('nunmai:connection-config:oauth-logout', remoteUrl),
  // Nunmai Cloud: one portal login powers discovery + silent per-agent sign-in
  // (cloud-auto-discovery Phase 3).
  cloud: {
    status: () => ipcRenderer.invoke('nunmai:cloud:status'),
    login: () => ipcRenderer.invoke('nunmai:cloud:login'),
    logout: () => ipcRenderer.invoke('nunmai:cloud:logout'),
    discover: org => ipcRenderer.invoke('nunmai:cloud:discover', org),
    agentSignIn: dashboardUrl => ipcRenderer.invoke('nunmai:cloud:agent-sign-in', dashboardUrl)
  },
  profile: {
    get: () => ipcRenderer.invoke('nunmai:profile:get'),
    remember: name => ipcRenderer.invoke('nunmai:profile:remember', name),
    set: name => ipcRenderer.invoke('nunmai:profile:set', name)
  },
  api: request => ipcRenderer.invoke('nunmai:api', request),
  notify: payload => ipcRenderer.invoke('nunmai:notify', payload),
  requestMicrophoneAccess: () => ipcRenderer.invoke('nunmai:requestMicrophoneAccess'),
  readWindowBelow: () => ipcRenderer.invoke('nunmai:window:readBelow'),
  readFileDataUrl: filePath => ipcRenderer.invoke('nunmai:readFileDataUrl', filePath),
  readFileDataUrlForAttach: filePath => ipcRenderer.invoke('nunmai:readFileDataUrlForAttach', filePath),
  dataUrlReadMax: {
    get: () => ipcRenderer.invoke('nunmai:data-url-read-max:get'),
    set: maxMb => ipcRenderer.invoke('nunmai:data-url-read-max:set', maxMb)
  },
  readFileText: filePath => ipcRenderer.invoke('nunmai:readFileText', filePath),
  readPluginSource: (filePath: string) => ipcRenderer.invoke('nunmai:readPluginSource', filePath),
  selectPaths: options => ipcRenderer.invoke('nunmai:selectPaths', options),
  selectSavePath: options => ipcRenderer.invoke('nunmai:selectSavePath', options),
  writeClipboard: text => ipcRenderer.invoke('nunmai:writeClipboard', text),
  readClipboard: () => ipcRenderer.invoke('nunmai:readClipboard'),
  saveGatewayFile: payload => ipcRenderer.invoke('nunmai:saveGatewayFile', payload),
  saveImageFromUrl: url => ipcRenderer.invoke('nunmai:saveImageFromUrl', url),
  contextMenuEdit: command => ipcRenderer.invoke('nunmai:context-menu:edit', command),
  contextMenuCopyImage: () => ipcRenderer.invoke('nunmai:context-menu:copy-image'),
  contextMenuSpellcheck: action => ipcRenderer.invoke('nunmai:context-menu:spellcheck', action),
  contextMenuGuestAddWord: payload => ipcRenderer.invoke('nunmai:context-menu:guest-add-word', payload),
  onContextMenuSpellcheck: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('nunmai:context-menu-spellcheck', listener)

    return () => ipcRenderer.removeListener('nunmai:context-menu-spellcheck', listener)
  },
  saveImageBuffer: (data, ext) => ipcRenderer.invoke('nunmai:saveImageBuffer', { data, ext }),
  saveClipboardImage: () => ipcRenderer.invoke('nunmai:saveClipboardImage'),
  getPathForFile: file => {
    try {
      return webUtils.getPathForFile(file) || ''
    } catch {
      return ''
    }
  },
  normalizePreviewTarget: (target, baseDir) => ipcRenderer.invoke('nunmai:normalizePreviewTarget', target, baseDir),
  watchPreviewFile: url => ipcRenderer.invoke('nunmai:watchPreviewFile', url),
  watchDirectory: dir => ipcRenderer.invoke('nunmai:watchDirectory', dir),
  stopPreviewFileWatch: id => ipcRenderer.invoke('nunmai:stopPreviewFileWatch', id),
  setActiveWork: payload => ipcRenderer.send('nunmai:active-work', payload),
  setTitleBarTheme: payload => ipcRenderer.send('nunmai:titlebar-theme', payload),
  setNativeTheme: mode => ipcRenderer.send('nunmai:native-theme', mode),
  setTranslucency: payload => ipcRenderer.send('nunmai:translucency', payload),
  setKeepAwake: on => ipcRenderer.send('nunmai:keep-awake', on),
  setDisableF12: blocked => ipcRenderer.send('nunmai:devtools:disable-f12', blocked),
  setPreviewShortcutActive: active => ipcRenderer.send('nunmai:previewShortcutActive', Boolean(active)),
  openExternal: url => ipcRenderer.invoke('nunmai:openExternal', url),
  openPreviewInBrowser: url => ipcRenderer.invoke('nunmai:openPreviewInBrowser', url),
  reachPreviewUrl: url => ipcRenderer.invoke('nunmai:preview:reach', url),
  setActiveConnectionRoute: route => ipcRenderer.send('nunmai:connection:active-route', route),
  fetchLinkTitle: url => ipcRenderer.invoke('nunmai:fetchLinkTitle', url),
  resolveFavicon: url => ipcRenderer.invoke('nunmai:resolveFavicon', url),
  sanitizeWorkspaceCwd: cwd => ipcRenderer.invoke('nunmai:workspace:sanitize', cwd),
  settings: {
    getDefaultProjectDir: () => ipcRenderer.invoke('nunmai:setting:defaultProjectDir:get'),
    setDefaultProjectDir: dir => ipcRenderer.invoke('nunmai:setting:defaultProjectDir:set', dir),
    pickDefaultProjectDir: () => ipcRenderer.invoke('nunmai:setting:defaultProjectDir:pick')
  },
  zoom: {
    // Current zoom of this window, as { level, percent }.
    get: () => ipcRenderer.invoke('nunmai:zoom:get'),
    // Synchronous zoom factor (1 = 100%). Coordinate math needs it in the
    // same tick as the event it converts, so no IPC round-trip here.
    factor: () => webFrame.getZoomFactor(),
    setPercent: percent => ipcRenderer.send('nunmai:zoom:set-percent', percent),
    // Fires on every zoom change, including the Ctrl/Cmd +/-/0 shortcuts,
    // so the settings UI can stay in sync with the keyboard.
    onChanged: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('nunmai:zoom:changed', listener)

      return () => ipcRenderer.removeListener('nunmai:zoom:changed', listener)
    }
  },
  revealLogs: () => ipcRenderer.invoke('nunmai:logs:reveal'),
  getRecentLogs: () => ipcRenderer.invoke('nunmai:logs:recent'),
  // Fire-and-forget: persists a renderer error-boundary catch (with component
  // stack) to desktop.log so crashes survive the window (#79428).
  reportRendererError: report => ipcRenderer.send('nunmai:logs:renderer-error', report),
  readDir: dirPath => ipcRenderer.invoke('nunmai:fs:readDir', dirPath),
  gitRoot: startPath => ipcRenderer.invoke('nunmai:fs:gitRoot', startPath),
  revealPath: targetPath => ipcRenderer.invoke('nunmai:fs:reveal', targetPath),
  openDir: dirPath => ipcRenderer.invoke('nunmai:fs:openDir', dirPath),
  desktopPluginsRoot: () => ipcRenderer.invoke('nunmai:fs:desktopPluginsRoot'),
  logsRoot: () => ipcRenderer.invoke('nunmai:fs:logsRoot'),
  agentPluginsRoot: () => ipcRenderer.invoke('nunmai:fs:agentPluginsRoot'),
  renamePath: (targetPath, newName) => ipcRenderer.invoke('nunmai:fs:rename', targetPath, newName),
  writeTextFile: (filePath, content) => ipcRenderer.invoke('nunmai:fs:writeText', filePath, content),
  trashPath: targetPath => ipcRenderer.invoke('nunmai:fs:trash', targetPath),
  git: {
    worktreeList: repoPath => ipcRenderer.invoke('nunmai:git:worktreeList', repoPath),
    worktreeAdd: (repoPath, options) => ipcRenderer.invoke('nunmai:git:worktreeAdd', repoPath, options),
    worktreeRemove: (repoPath, worktreePath, options) =>
      ipcRenderer.invoke('nunmai:git:worktreeRemove', repoPath, worktreePath, options),
    branchSwitch: (repoPath, branch) => ipcRenderer.invoke('nunmai:git:branchSwitch', repoPath, branch),
    branchList: repoPath => ipcRenderer.invoke('nunmai:git:branchList', repoPath),
    baseBranchList: repoPath => ipcRenderer.invoke('nunmai:git:baseBranchList', repoPath),
    repoStatus: repoPath => ipcRenderer.invoke('nunmai:git:repoStatus', repoPath),
    fileDiff: (repoPath, filePath) => ipcRenderer.invoke('nunmai:git:fileDiff', repoPath, filePath),
    scanRepos: (roots, options) => ipcRenderer.invoke('nunmai:git:scanRepos', roots, options),
    review: {
      list: (repoPath, scope, baseRef) => ipcRenderer.invoke('nunmai:git:review:list', repoPath, scope, baseRef),
      diff: (repoPath, filePath, scope, baseRef, staged) =>
        ipcRenderer.invoke('nunmai:git:review:diff', repoPath, filePath, scope, baseRef, staged),
      stage: (repoPath, filePath) => ipcRenderer.invoke('nunmai:git:review:stage', repoPath, filePath),
      unstage: (repoPath, filePath) => ipcRenderer.invoke('nunmai:git:review:unstage', repoPath, filePath),
      revert: (repoPath, filePath) => ipcRenderer.invoke('nunmai:git:review:revert', repoPath, filePath),
      revParse: (repoPath, ref) => ipcRenderer.invoke('nunmai:git:review:revParse', repoPath, ref),
      commit: (repoPath, message, push) => ipcRenderer.invoke('nunmai:git:review:commit', repoPath, message, push),
      commitContext: repoPath => ipcRenderer.invoke('nunmai:git:review:commitContext', repoPath),
      push: repoPath => ipcRenderer.invoke('nunmai:git:review:push', repoPath),
      shipInfo: repoPath => ipcRenderer.invoke('nunmai:git:review:shipInfo', repoPath),
      prList: (repoPath, branches, numbers) =>
        ipcRenderer.invoke('nunmai:git:review:prList', repoPath, branches, numbers),
      fetchPrComment: (repoPath, url) => ipcRenderer.invoke('nunmai:git:review:fetchPrComment', repoPath, url),
      createPr: repoPath => ipcRenderer.invoke('nunmai:git:review:createPr', repoPath)
    }
  },
  terminal: {
    cwd: id => ipcRenderer.invoke('nunmai:terminal:cwd', id),
    dispose: id => ipcRenderer.invoke('nunmai:terminal:dispose', id),
    resize: (id, size) => ipcRenderer.invoke('nunmai:terminal:resize', id, size),
    start: options => ipcRenderer.invoke('nunmai:terminal:start', options),
    write: (id, data) => ipcRenderer.invoke('nunmai:terminal:write', id, data),
    onData: (id, callback) => {
      const channel = `nunmai:terminal:${id}:data`
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on(channel, listener)

      return () => ipcRenderer.removeListener(channel, listener)
    },
    onExit: (id, callback) => {
      const channel = `nunmai:terminal:${id}:exit`
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on(channel, listener)

      return () => ipcRenderer.removeListener(channel, listener)
    }
  },
  onClosePreviewRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('nunmai:close-preview-requested', listener)

    return () => ipcRenderer.removeListener('nunmai:close-preview-requested', listener)
  },
  onPreviewNav: callback => {
    const listener = (_event, command) => callback(command)
    ipcRenderer.on('nunmai:preview-nav', listener)

    return () => ipcRenderer.removeListener('nunmai:preview-nav', listener)
  },
  onOpenFolderRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('nunmai:open-folder-requested', listener)

    return () => ipcRenderer.removeListener('nunmai:open-folder-requested', listener)
  },
  onOpenUpdatesRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('nunmai:open-updates', listener)

    return () => ipcRenderer.removeListener('nunmai:open-updates', listener)
  },
  onDeepLink: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('nunmai:deep-link', listener)

    return () => ipcRenderer.removeListener('nunmai:deep-link', listener)
  },
  signalDeepLinkReady: () => ipcRenderer.invoke('nunmai:deep-link-ready'),
  probePluginRepo: payload => ipcRenderer.invoke('nunmai:plugin:probe', payload),
  installDesktopPlugin: payload => ipcRenderer.invoke('nunmai:plugin:installDesktop', payload),
  onWindowStateChanged: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('nunmai:window-state-changed', listener)

    return () => ipcRenderer.removeListener('nunmai:window-state-changed', listener)
  },
  onFocusSession: callback => {
    const listener = (_event, sessionId) => callback(sessionId)
    ipcRenderer.on('nunmai:focus-session', listener)

    return () => ipcRenderer.removeListener('nunmai:focus-session', listener)
  },
  onNotificationAction: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('nunmai:notification-action', listener)

    return () => ipcRenderer.removeListener('nunmai:notification-action', listener)
  },
  onNotificationActivate: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('nunmai:notification-activate', listener)

    return () => ipcRenderer.removeListener('nunmai:notification-activate', listener)
  },
  onPreviewFileChanged: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('nunmai:preview-file-changed', listener)

    return () => ipcRenderer.removeListener('nunmai:preview-file-changed', listener)
  },
  onBackendExit: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('nunmai:backend-exit', listener)

    return () => ipcRenderer.removeListener('nunmai:backend-exit', listener)
  },
  // Soft gateway-mode apply finished tearing down the primary backend. Renderer
  // should wipe session lists + re-dial without a window reload.
  onConnectionApplied: callback => {
    const listener = () => callback()
    ipcRenderer.on('nunmai:connection:applied', listener)

    return () => ipcRenderer.removeListener('nunmai:connection:applied', listener)
  },
  onPowerResume: callback => {
    const listener = () => callback()
    ipcRenderer.on('nunmai:power-resume', listener)

    return () => ipcRenderer.removeListener('nunmai:power-resume', listener)
  },
  // AC ↔ battery transitions; renderers slow their backstop polls on battery.
  getOnBattery: () => ipcRenderer.invoke('nunmai:power-battery:get'),
  onBatteryChanged: callback => {
    const listener = (_event, onBattery) => callback(Boolean(onBattery))
    ipcRenderer.on('nunmai:power-battery', listener)

    return () => ipcRenderer.removeListener('nunmai:power-battery', listener)
  },
  onBootProgress: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('nunmai:boot-progress', listener)

    return () => ipcRenderer.removeListener('nunmai:boot-progress', listener)
  },
  // First-launch bootstrap progress -- emitted by the install.ps1 stage
  // runner in main.ts (apps/desktop/electron/bootstrap-runner.ts).
  // Renderer's install overlay subscribes to live events and queries the
  // current snapshot via getBootstrapState() to recover after a devtools
  // reload mid-bootstrap.
  getBootstrapState: () => ipcRenderer.invoke('nunmai:bootstrap:get'),
  continueBootstrapLocal: () => ipcRenderer.invoke('nunmai:bootstrap:continue-local'),
  resetBootstrap: () => ipcRenderer.invoke('nunmai:bootstrap:reset'),
  repairBootstrap: () => ipcRenderer.invoke('nunmai:bootstrap:repair'),
  cancelBootstrap: () => ipcRenderer.invoke('nunmai:bootstrap:cancel'),
  onBootstrapEvent: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('nunmai:bootstrap:event', listener)

    return () => ipcRenderer.removeListener('nunmai:bootstrap:event', listener)
  },
  getVersion: () => ipcRenderer.invoke('nunmai:version'),
  getRemoteDisplayReason: () => ipcRenderer.invoke('nunmai:get-remote-display-reason'),
  uninstall: {
    summary: () => ipcRenderer.invoke('nunmai:uninstall:summary'),
    run: mode => ipcRenderer.invoke('nunmai:uninstall:run', { mode })
  },
  updates: {
    check: () => ipcRenderer.invoke('nunmai:updates:check'),
    apply: opts => ipcRenderer.invoke('nunmai:updates:apply', opts),
    getBranch: () => ipcRenderer.invoke('nunmai:updates:branch:get'),
    setBranch: name => ipcRenderer.invoke('nunmai:updates:branch:set', name),
    onProgress: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('nunmai:updates:progress', listener)

      return () => ipcRenderer.removeListener('nunmai:updates:progress', listener)
    }
  },
  themes: {
    fetchMarketplace: id => ipcRenderer.invoke('nunmai:vscode-theme:fetch', id),
    searchMarketplace: query => ipcRenderer.invoke('nunmai:vscode-theme:search', query)
  },
  // Find-in-page (Ctrl/Cmd+F): delegates to Electron's
  // webContents.findInPage on the IPC sender's window so a Cmd+F pressed
  // in a secondary session window searches THAT window, not the primary.
  // `onFoundInPage` returns the unsubscribe fn; the renderer wires it via
  // `initFindInPageListener` in store/find-in-page.ts and tears it down
  // when the FindBar unmounts.
  findInPage: (query, options) => ipcRenderer.invoke('nunmai:find-in-page', query, options),
  stopFindInPage: () => ipcRenderer.invoke('nunmai:stop-find-in-page'),
  onFoundInPage: callback => {
    const listener = (_event, result) => callback(result)
    ipcRenderer.on('nunmai:found-in-page', listener)

    return () => ipcRenderer.removeListener('nunmai:found-in-page', listener)
  },
  // Main-process `before-input-event` forwards Ctrl/Cmd+F here so renderer
  // can open the FindBar even when the GTK compositor has already grabbed
  // the chord at the windowing layer (#81727).
  onOpenFindBarRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('nunmai:open-find-bar', listener)

    return () => ipcRenderer.removeListener('nunmai:open-find-bar', listener)
  }
})
