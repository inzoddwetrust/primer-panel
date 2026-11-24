// The runtime configuration, provided to the pages (./config, src/main.ts).

import { inject, type InjectionKey } from 'vue'
import type { RuntimeConfig } from './config'

export const RUNTIME_CONFIG: InjectionKey<RuntimeConfig> = Symbol('runtime-config')

export function useRuntimeConfig(): RuntimeConfig {
  const config = inject(RUNTIME_CONFIG)
  if (config === undefined) {
    throw new Error('no runtime configuration is provided')
  }
  return config
}
