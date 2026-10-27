import React from 'react';
import { shallow } from 'enzyme';
import EditTaskForm from '../EditTaskForm';
import TaskOptionsPluginItems from '../TaskOptionsPluginItems';
import PluginsAPI from '../../classes/plugins/API';

const defaultPreset = {id: 1, name: "Default", options: [{name: "dsm", value: true}], system: true};
const customPreset = {id: -1, name: "(Custom)", options: [], system: true};

// A form as it is once the nodes and presets are loaded
const loadedForm = props => {
  const wrapper = shallow(<EditTaskForm {...props} />);
  const node = {id: 1, key: 1, options: [{name: "dsm"}, {name: "crop"}]};
  wrapper.setState({
    loadedProcessingNodes: true, processingNodes: [node], selectedNode: node,
    loadedPresets: true, presets: [customPreset, defaultPreset], selectedPreset: defaultPreset
  });
  return wrapper;
};

describe('<EditTaskForm />', () => {
  afterEach(() => {
    PluginsAPI.events.removeAllListeners("Dashboard::addTaskOptionsFormItem");
  });

  it('renders without exploding', () => {
    const wrapper = shallow(<EditTaskForm />);
    expect(wrapper.exists()).toBe(true);
  })

  it('has no plugin items when no plugin adds any', () => {
    expect(loadedForm().find(TaskOptionsPluginItems).length).toBe(0);
  })

  it('shows the items plugins add, with what they need to know of the task', () => {
    PluginsAPI.Dashboard.addTaskOptionsFormItem(() => null);
    const getFiles = () => [];
    const items = loadedForm({getFiles, filesCount: 3}).find(TaskOptionsPluginItems);

    expect(items.length).toBe(1);
    const { context, taskOptions } = items.props().itemProps;
    expect(context.mode).toBe("new");
    expect(context.getFiles).toBe(getFiles);
    expect(context.filesCount).toBe(3);
    expect(context.preset).toBe(defaultPreset);
    expect(taskOptions.getOptions()).toEqual([{name: "dsm", value: true}]);
  })

  it('tells plugins when the task exists already', () => {
    const task = {id: "1", name: "Task", tags: [], options: []};
    expect(loadedForm({task}).instance().getPluginContext()).toMatchObject({mode: "edit", task});
  })

  it('puts the options plugins set in the custom preset, as the user would', () => {
    const wrapper = loadedForm();
    const taskOptions = wrapper.instance().getPluginTaskOptions();

    expect(taskOptions.setOption("crop", "0")).toBe(true);
    expect(wrapper.state().selectedPreset).toMatchObject({id: -1, options: [{name: "dsm", value: true}, {name: "crop", value: "0"}]});
    expect(wrapper.state().presets.filter(p => p.id === -1).length).toBe(1);
    expect(defaultPreset.options).toEqual([{name: "dsm", value: true}]);

    expect(taskOptions.resetOption("dsm")).toBe(true);
    expect(wrapper.instance().getPluginTaskOptions().getOptions()).toEqual([{name: "crop", value: "0"}]);
    expect(taskOptions.setOption("not-on-this-node", "1")).toBe(false);
  })
});
