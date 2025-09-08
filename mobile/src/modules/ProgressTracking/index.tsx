import React, { useEffect, useState } from 'react';
import { View, Text, Button } from 'react-native';
import { getBiometrics, getRoutine } from '../../services/api';

// ProgressTracking module shows user's progress and statistics.
export default function ProgressTracking() {
  const [hr, setHr] = useState<number | null>(null);
  const [steps, setSteps] = useState<number | null>(null);
  const [routine, setRoutine] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    try {
      setError(null);
      const bio = await getBiometrics();
      setHr(bio.data?.heart_rate_bpm ?? null);
      setSteps(bio.data?.steps ?? null);
      const r = await getRoutine('demo-user');
      setRoutine(r.data);
    } catch (e: any) {
      setError(e?.message || 'Network error');
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  return (
    <View style={{ padding: 16 }}>
      <Text style={{ fontSize: 18, fontWeight: 'bold' }}>Progress Tracking</Text>
      {error && <Text style={{ color: 'red' }}>{error}</Text>}
      <Text>Heart Rate: {hr ?? '-'} bpm</Text>
      <Text>Steps: {steps ?? '-'}</Text>
      <Text style={{ marginTop: 8 }}>Next Routine: {routine?.routine_id ?? '-'}</Text>
      <Button title="Refresh" onPress={refresh} />
    </View>
  );
}
