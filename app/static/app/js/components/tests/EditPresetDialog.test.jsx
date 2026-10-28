import React from 'react';
import { shallow, mount } from 'enzyme';
import EditPresetDialog from '../EditPresetDialog';
import PluginsAPI from '../../classes/plugins/API';
import $ from 'jquery';

// Bootstrap's tooltips are not loaded in the tests
$.fn.tooltip = function(){ return this; };

// The dialog's modal needs Bootstrap
jest.mock('../FormDialog', () => props => <div>{props.children}</div>);

const presetMock = require('../../tests/utils/MockLoader').load("preset.json");

describe('<EditPresetDialog />', () => {
  afterEach(() => {
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

  it('tells plugins the task, and saves the values their controls set', async () => {
    let asked;
    PluginsAPI.Dashboard.addTaskOptionControl(args => {
      if (args.option.name !== "boundary") return null;
      asked = args;
      return <button className="plugin-control" onClick={() => args.setValue('{"type": "Polygon"}')} />;
    });
    const task = {id: "1"};
    const wrapper = mount(<EditPresetDialog
             preset={{id: -1, name: "(Custom)", options: [], system: true}}
             availableOptions={[{name: "crop", type: "float", value: "3", domain: "positive float", help: "Crop"},
                                {name: "boundary", type: "string", value: "", domain: "json", help: "Boundary"}]}
             task={task}
             getPhotoPositions={() => [[11, 46]]}
             saveAction={() => {}}
             deleteAction={() => {}}
        />);
    await new Promise(resolve => setTimeout(resolve, 0));
    wrapper.update();

    expect(asked.task).toBe(task);
    expect(asked.getPhotoPositions()).toEqual([[11, 46]]);
    wrapper.find('.plugin-control').simulate('click');
    expect(wrapper.instance().getFormData().options).toEqual([{name: "boundary", value: '{"type": "Polygon"}'}]);
  })
});
