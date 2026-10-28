import React from 'react';
import { shallow, mount } from 'enzyme';
import ProcessingNodeOption from '../ProcessingNodeOption';
import PluginsAPI from '../../classes/plugins/API';
import $ from 'jquery';

// Bootstrap's tooltips are not loaded in the tests
$.fn.tooltip = function(){ return this; };

const replies = () => new Promise(resolve => setTimeout(resolve, 0));

describe('<ProcessingNodeOption />', () => {
  afterEach(() => {
    PluginsAPI.events.removeAllListeners("Dashboard::addTaskOptionControl");
  });

  it('renders without exploding', () => {
    const wrapper = shallow(<ProcessingNodeOption name="test" defaultValue={true} />);
    expect(wrapper.exists()).toBe(true);
  })

  it('shows the controls plugins add beside it, which can read and set its value', async () => {
    PluginsAPI.Dashboard.addTaskOptionControl(args => {
      if (args.option.name !== "boundary") return null;
      return <button className="plugin-control" onClick={() => args.setValue(args.getValue() + "!")}>{args.option.domain}</button>;
    });
    const boundary = mount(<ProcessingNodeOption name="boundary" defaultValue="" domain="json" value="{}" />);
    const crop = mount(<ProcessingNodeOption name="crop" defaultValue="3" />);
    await replies();
    boundary.update();
    crop.update();

    expect(crop.find('.plugin-control').length).toBe(0);
    expect(boundary.find('.plugin-control').text()).toBe("json");
    boundary.find('.plugin-control').simulate('click');
    expect(boundary.instance().getValue()).toBe("{}!");
  })

  it('tells plugins the task being edited and the photo positions of a new one', () => {
    const asked = [];
    PluginsAPI.Dashboard.addTaskOptionControl(args => { asked.push(args); return null; });
    const task = {id: "1"};
    mount(<ProcessingNodeOption name="boundary" defaultValue="" task={task} />);
    mount(<ProcessingNodeOption name="boundary" defaultValue="" getPhotoPositions={() => [[11, 46]]} />);

    expect(asked[0].task).toBe(task);
    expect(asked[0].getPhotoPositions()).toEqual([]);
    expect(asked[1].task).toBe(null);
    expect(asked[1].getPhotoPositions()).toEqual([[11, 46]]);
  })

  it('ignores a control that comes after the option is gone', async () => {
    jest.spyOn(console, 'error').mockImplementation(() => {});
    PluginsAPI.Dashboard.addTaskOptionControl(() => <button />);
    mount(<ProcessingNodeOption name="boundary" defaultValue="" />).unmount();
    await replies();

    expect(console.error).not.toHaveBeenCalled();
    console.error.mockRestore();
  })

  it('sets a value as if the user had typed it', () => {
    const option = mount(<ProcessingNodeOption name="feature-type" defaultValue="dspsift" type="enum" domain={["dspsift", "sift"]} />);
    option.instance().setValue("sift");
    expect(option.instance().getValue()).toBe("sift");
    option.instance().setValue("dspsift");
    expect(option.instance().getValue()).toBe(undefined);

    const flag = mount(<ProcessingNodeOption name="fast-orthophoto" defaultValue={false} type="bool" />);
    flag.instance().setValue(true);
    expect(flag.instance().getValue()).toBe(true);
    flag.instance().setValue(false);
    expect(flag.instance().getValue()).toBe(undefined);
  })
});
