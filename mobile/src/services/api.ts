import axios from 'axios';

// Simple API client targeting the embedded FastAPI server.
const BASE_URL = process.env.EXPO_PUBLIC_API_URL || 'http://192.168.0.10:8000';

export const api = axios.create({ baseURL: BASE_URL, timeout: 5000 });

export async function getRoutine(userId: string) {
  const res = await api.post('/routine', { user_id: userId });
  return res.data;
}

export async function getBiometrics() {
  const res = await api.post('/biometrics', {});
  return res.data;
}

export async function getPosture() {
  const res = await api.post('/posture', {});
  return res.data;
}
