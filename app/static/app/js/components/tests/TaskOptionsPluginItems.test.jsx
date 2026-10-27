import React from 'react';
import { mount } from 'enzyme';
import TaskOptionsPluginItems from '../TaskOptionsPluginItems';
import PluginsAPI from '../../classes/plugins/API';

const hook = "addTaskOptionsFormItem";
const replies = () => new Promise(resolve => setTimeout(resolve, 0));

describe('<TaskOptionsPluginItems />', () => {
  afterEach(() => {
    PluginsAPI.events.removeAllListeners(`Dashboard::${hook}`);
  });

  it('knows whether a plugin uses a hook', () => {
    expect(TaskOptionsPluginItems.hasListeners(hook)).toBe(false);
    PluginsAPI.Dashboard.addTaskOptionsFormItem(() => null);
    expect(TaskOptionsPluginItems.hasListeners(hook)).toBe(true);
  });

  it('renders the components plugins return, with the item props', async () => {
    PluginsAPI.Dashboard.addTaskOptionsFormItem(args => props => <span className="item">{args.context.mode} {props.value}</span>);
    const wrapper = mount(<TaskOptionsPluginItems hook={hook} args={{context: {mode: "new"}}} itemProps={{value: 42}} />);
    await replies();
    wrapper.update();

    expect(wrapper.find('.item').text()).toBe("new 42");
  });

  it('renders elements and lists of them, and leaves out anything else', async () => {
    PluginsAPI.Dashboard.addTaskOptionsFormItem(() => [<b key="1" className="item">one</b>, <b key="2" className="item">two</b>]);
    PluginsAPI.Dashboard.addTaskOptionsFormItem(() => "not a component");
    PluginsAPI.Dashboard.addTaskOptionsFormItem(() => null);
    const wrapper = mount(<TaskOptionsPluginItems hook={hook} />);
    await replies();
    wrapper.update();

    expect(wrapper.find('.item').map(item => item.text())).toEqual(["one", "two"]);
  });

  it('renders nothing when no plugin returns anything', async () => {
    PluginsAPI.Dashboard.addTaskOptionsFormItem(() => null);
    const wrapper = mount(<TaskOptionsPluginItems hook={hook} />);
    await replies();
    wrapper.update();

    expect(wrapper.html()).toBe(null);
  });

  it('keeps the other plugins items when one fails to render', async () => {
    jest.spyOn(console, 'error').mockImplementation(() => {});
    jest.spyOn(console, 'warn').mockImplementation(() => {});
    const Broken = () => { throw new Error("broken"); };
    PluginsAPI.Dashboard.addTaskOptionsFormItem(() => Broken);
    PluginsAPI.Dashboard.addTaskOptionsFormItem(() => () => <span className="item">works</span>);
    const wrapper = mount(<TaskOptionsPluginItems hook={hook} />);
    await replies();
    wrapper.update();

    expect(wrapper.find('.item').text()).toBe("works");
    console.error.mockRestore();
    console.warn.mockRestore();
  });

  it('does not fail when a plugin throws as it is asked', () => {
    jest.spyOn(console, 'warn').mockImplementation(() => {});
    PluginsAPI.Dashboard.addTaskOptionsFormItem(() => { throw new Error("broken"); });

    expect(() => mount(<TaskOptionsPluginItems hook={hook} />)).not.toThrow();
    console.warn.mockRestore();
  });
});
