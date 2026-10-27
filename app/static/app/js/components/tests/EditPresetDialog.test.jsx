import React from 'react';
import { shallow, mount } from 'enzyme';
import EditPresetDialog from '../EditPresetDialog';
import TaskOptionsPluginItems from '../TaskOptionsPluginItems';
import PluginsAPI from '../../classes/plugins/API';
import $ from 'jquery';

// Bootstrap's tooltips are not loaded in the tests
$.fn.tooltip = function(){ return this; };

const presetMock = require('../../tests/utils/MockLoader').load("preset.json");

// The dialog's modal needs Bootstrap
jest.mock('../FormDialog', () => props => <div>{props.children}</div>);

const availableOptions = [
  {name: "crop", type: "float", value: "3", domain: "positive float", help: "Crop"},
  {name: "boundary", type: "string", value: "", domain: "json", help: "Boundary"}
];
const replies = () => new Promise(resolve => setTimeout(resolve, 0));

const mountDialog = () => mount(<EditPresetDialog
  preset={{id: -1, name: "(Custom)", options: [], system: true}}
  availableOptions={availableOptions}
  pluginContext={{mode: "new"}}
  saveAction={() => {}}
  deleteAction={() => {}}
/>);

describe('<EditPresetDialog />', () => {
  afterEach(() => {
    PluginsAPI.events.removeAllListeners("Dashboard::addTaskOptionsPanelItem");
    PluginsAPI.events.removeAllListeners("Dashboard::addTaskOptionControl");
  });

  it('renders without exploding', () => {
    const wrapper = shallow(<EditPresetDialog 
             preset={presetMock}
             availableOptions={[]}
             saveAction={() => {}}
             deleteAction={() => {}}
        />);
    expect(wrapper.exists()).toBe(true);
  })

  it('is unchanged when no plugin adds to it', () => {
    const wrapper = mountDialog();
    expect(wrapper.find(TaskOptionsPluginItems).length).toBe(0);
    expect(wrapper.find('ProcessingNodeOption').first().props().taskOptions).toBe(undefined);
  })

  it('shows the items plugins add, which can change the options as the user would', async () => {
    PluginsAPI.Dashboard.addTaskOptionsPanelItem(() => props =>
      <button className="plugin-item" onClick={() => props.taskOptions.setOption("crop", "0")}>{props.context.mode}</button>);
    const wrapper = mountDialog();
    await replies();
    wrapper.update();

    expect(wrapper.find('.plugin-item').text()).toBe("new");
    wrapper.find('.plugin-item').simulate('click');
    expect(wrapper.instance().getFormData().options).toEqual([{name: "crop", value: "0"}]);
  })

  it('gives the task options to the controls plugins add to an option', async () => {
    PluginsAPI.Dashboard.addTaskOptionControl(args => {
      if (args.option.name !== "boundary") return;
      return props => <button className="plugin-control" onClick={() => {
        props.setValue('{"type": "Polygon"}');
        props.taskOptions.setOption("crop", "0");
      }} />;
    });
    const wrapper = mountDialog();
    await replies();
    wrapper.update();

    expect(wrapper.find('.plugin-control').length).toBe(1);
    wrapper.find('.plugin-control').simulate('click');
    const options = wrapper.instance().getFormData().options;
    expect(options).toContainEqual({name: "boundary", value: '{"type": "Polygon"}'});
    expect(options).toContainEqual({name: "crop", value: "0"});
  })
});
