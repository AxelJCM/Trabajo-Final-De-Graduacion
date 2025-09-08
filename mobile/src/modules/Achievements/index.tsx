import React from 'react';
import { View, Text } from 'react-native';

// Achievements module provides gamification with badges and goals.
const badges = [
  { id: 'streak3', name: '3-Day Streak' },
  { id: 'hrzone', name: 'HR Zone Master' },
  { id: 'starter', name: 'First Routine' },
];

export default function Achievements() {
  return (
    <View style={{ padding: 16 }}>
      <Text style={{ fontSize: 18, fontWeight: 'bold' }}>Achievements</Text>
      {badges.map((b) => (
        <Text key={b.id}>🏅 {b.name}</Text>
      ))}
    </View>
  );
}
