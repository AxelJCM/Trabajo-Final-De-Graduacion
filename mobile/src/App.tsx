import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { SafeAreaView, View, Text } from 'react-native';
import ProgressTracking from './modules/ProgressTracking';
import Achievements from './modules/Achievements';
import Settings from './modules/Settings';

const Stack = createNativeStackNavigator();

export default function App() {
  return (
    <NavigationContainer>
      <Stack.Navigator initialRouteName="Progress">
        <Stack.Screen name="Progress" component={ProgressTracking} options={{ title: 'Progreso' }} />
        <Stack.Screen name="Achievements" component={Achievements} />
        <Stack.Screen name="Settings" component={Settings} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}
