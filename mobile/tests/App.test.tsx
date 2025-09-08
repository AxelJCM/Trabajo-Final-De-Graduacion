import React from 'react';
import { render } from '@testing-library/react-native';
import App from '../src/App';

test('renders navigation', () => {
  const { getByText } = render(<App />);
  expect(getByText('Progress')).toBeTruthy();
});
