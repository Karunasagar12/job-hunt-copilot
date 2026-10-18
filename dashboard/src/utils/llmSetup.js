export const initialLlmSetupState = { saved: false, tested: false };

export function llmSetupReducer(state = initialLlmSetupState, action) {
  if (action.type === 'edit') return initialLlmSetupState;
  if (action.type === 'saved') return { saved: true, tested: false };
  if (action.type === 'tested') return { saved: state.saved, tested: state.saved && action.ok === true };
  return state;
}
