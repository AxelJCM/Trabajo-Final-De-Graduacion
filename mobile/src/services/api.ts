import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';

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

export const getConfig = async () => {
  try {
    const res = await api.get('/config');
    const data = res.data.data;
    await AsyncStorage.setItem('config', JSON.stringify(data));
    return data;
  } catch (e) {
    const cached = await AsyncStorage.getItem('config');
    return cached ? JSON.parse(cached) : null;
  }
};

export const saveConfig = async (config: { language?: string; intensity?: string; units?: string; tz?: string }, apiKey?: string) => {
  const headers: Record<string, string> = {};
  if (apiKey) headers['X-API-Key'] = apiKey;
  const res = await api.post('/config', { ...config }, { headers });
  const data = res.data.data;
  await AsyncStorage.setItem('config', JSON.stringify(data));
  return data;
};
