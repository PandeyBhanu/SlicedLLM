// API base configuration (override with NEXT_PUBLIC_* variables, see frontend/.env.example)
export const API_CONFIG = {
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1',
  apiKey: process.env.NEXT_PUBLIC_API_KEY || '',
  actorId: process.env.NEXT_PUBLIC_ACTOR_ID || '',
} as const;
