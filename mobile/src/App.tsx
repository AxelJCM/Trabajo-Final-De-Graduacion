import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { SafeAreaView, View, Text } from 'react-native';
import ProgressTracking from './modules/ProgressTracking';
import Achievements from './modules/Achievements';

const Stack = createNativeStackNavigator();

export default function App() {
  return (
    <NavigationContainer>
      <Stack.Navigator>
        <Stack.Screen name="Progress" component={ProgressTracking} />
        <Stack.Screen name="Achievements" component={Achievements} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}
