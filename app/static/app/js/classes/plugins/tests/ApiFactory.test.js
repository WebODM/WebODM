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
  it('gives every reply to its own trigger, when several triggers are waiting', async () => {
    const { api } = createApi();
    api.addItem(args => `first ${args.n}`);
    api.addItem(args => `second ${args.n}`);

    const replies = { 1: [], 2: [], 3: [] };
    [1, 2, 3].forEach(n => api.triggerAddItem({ n }, result => replies[n].push(result)));
    await nextTick();

    expect(replies).toEqual({
      1: ["first 1", "second 1"],
      2: ["first 2", "second 2"],
      3: ["first 3", "second 3"]
    });
  });

  it('waits for the replies of plugins whose dependencies load later', async () => {
    const { api } = createApi();
    api.addItem(["fast"], (args, dep) => dep);
    api.addItem(["slow"], (args, dep) => dep);

    const replies = [];
    api.triggerAddItem({}, result => replies.push(result));
    await new Promise(resolve => setTimeout(resolve, 50));

    expect(replies).toEqual(["fast", "slow"]);
  });

  it('stops listening once every listener has replied', async () => {
    const { events, api } = createApi();
    api.addItem(() => "item");

    api.triggerAddItem({}, () => {});
    expect(events.listeners("Test::addItem::Response").length).toBe(1);
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
