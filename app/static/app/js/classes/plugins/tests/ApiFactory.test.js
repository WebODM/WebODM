import { EventEmitter } from 'fbemitter';
import ApiFactory from '../ApiFactory';

// A plugin's dependencies load in 20 ms ("slow") or at once
jest.mock('SystemJS', () => ({
  import: dep => new Promise(resolve => setTimeout(() => resolve({ default: dep }), dep === "slow" ? 20 : 0))
}));

const createApi = () => {
  const events = new EventEmitter();
  const api = new ApiFactory(events).create({ namespace: "Test", endpoints: ["addItem"] });
  return { events, api };
};

const nextTick = () => new Promise(resolve => setTimeout(resolve, 0));

describe('ApiFactory', () => {
  it('gives each trigger its replies, also from plugins whose dependencies load later', async () => {
    const { api } = createApi();
    api.addItem(["fast"], (args, dep) => `${dep} ${args.n}`);
    api.addItem(["slow"], (args, dep) => `${dep} ${args.n}`);

    const replies = { 1: [], 2: [] };
    [1, 2].forEach(n => api.triggerAddItem({ n }, result => replies[n].push(result)));
    await new Promise(resolve => setTimeout(resolve, 50));

    expect(replies).toEqual({ 1: ["fast 1", "slow 1"], 2: ["fast 2", "slow 2"] });
  });

  it('stops listening once every listener has replied', async () => {
    const { events, api } = createApi();
    api.addItem(() => "item");

    api.triggerAddItem({}, () => {});
    await nextTick();
    expect(events.listeners("Test::addItem::Response").length).toBe(0);
  });

  it('does not wait for replies when nothing listens', () => {
    const { events, api } = createApi();
    const responseCb = jest.fn();

    api.triggerAddItem({}, responseCb);
    expect(events.listeners("Test::addItem::Response").length).toBe(0);
    expect(responseCb).not.toHaveBeenCalled();
  });
});
