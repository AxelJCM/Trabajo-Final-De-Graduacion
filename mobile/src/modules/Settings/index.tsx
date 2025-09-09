import React, { useEffect, useState } from 'react';
import { View, Text, TextInput, Button, StyleSheet, Alert } from 'react-native';
import { getConfig, saveConfig } from '../../services/api';

export default function Settings() {
  const [language, setLanguage] = useState('es');
  const [intensity, setIntensity] = useState('medium');
  const [units, setUnits] = useState('metric');
  const [tz, setTz] = useState('America/Costa_Rica');
  const [apiKey, setApiKey] = useState('');

  useEffect(() => {
    (async () => {
      const cfg = await getConfig();
      if (cfg) {
        setLanguage(cfg.language || 'es');
        setIntensity(cfg.intensity || 'medium');
        setUnits(cfg.units || 'metric');
        setTz(cfg.tz || 'America/Costa_Rica');
      }
    })();
  }, []);

  const onSave = async () => {
    try {
      const saved = await saveConfig({ language, intensity, units, tz }, apiKey || undefined);
      Alert.alert('Guardado', 'Configuración actualizada');
    } catch (e: any) {
      Alert.alert('Error', e?.message || 'No se pudo guardar');
    }
  };

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Configuración</Text>
      <Text>Language</Text>
      <TextInput style={styles.input} value={language} onChangeText={setLanguage} />
      <Text>Intensity</Text>
      <TextInput style={styles.input} value={intensity} onChangeText={setIntensity} />
      <Text>Units</Text>
      <TextInput style={styles.input} value={units} onChangeText={setUnits} />
      <Text>Timezone</Text>
      <TextInput style={styles.input} value={tz} onChangeText={setTz} />
      <Text>API Key (optional)</Text>
      <TextInput style={styles.input} value={apiKey} onChangeText={setApiKey} />
      <Button title="Guardar" onPress={onSave} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 16 },
  title: { fontSize: 20, fontWeight: '600', marginBottom: 12 },
  input: { borderWidth: 1, borderColor: '#ccc', padding: 8, marginBottom: 10, borderRadius: 6 }
});
