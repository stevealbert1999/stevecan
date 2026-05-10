export interface EventRecord {
  id: string;
  kind: string;
  source: string;
  payload: unknown;
  createdAt: string;
}

export interface MemoryFact {
  key: string;
  value: string;
  source: string;
  confidence: number;
  tags: string[];
  updatedAt: string;
}

export interface Suggestion {
  id: string;
  title: string;
  reason: string;
  priority: number;
  status: 'pending' | 'accepted' | 'dismissed';
}

export interface CapabilityRequest {
  id: string;
  goal: string;
  status: 'queued' | 'running' | 'failed' | 'completed';
  pipelineState: string;
  createdAt: string;
}

export interface DeviceState {
  deviceId: string;
  platform: string;
  status: 'online' | 'offline';
  lastSeen: string;
}
