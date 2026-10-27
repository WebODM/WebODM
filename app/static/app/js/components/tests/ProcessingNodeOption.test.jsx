import React from 'react';
import { shallow, mount } from 'enzyme';
import ProcessingNodeOption from '../ProcessingNodeOption';
import TaskOptionsPluginItems from '../TaskOptionsPluginItems';
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

  it('has no plugin controls unless it is given the task options', () => {
    PluginsAPI.Dashboard.addTaskOptionControl(() => () => <button className="plugin-control" />);
    const wrapper = shallow(<ProcessingNodeOption name="boundary" defaultValue="" domain="json" />);
    expect(wrapper.find(TaskOptionsPluginItems).length).toBe(0);
  })

  it('shows the controls plugins add to it, which can set its value', async () => {
    PluginsAPI.Dashboard.addTaskOptionControl(args => {
      if (args.option.name !== "boundary") return;
      return props => <button className="plugin-control" onClick={() => props.setValue('{"type": "Polygon"}')}>{props.context.mode}</button>;
    });
    const context = {mode: "edit"};
    const boundary = mount(<ProcessingNodeOption name="boundary" defaultValue="" domain="json" pluginContext={context} taskOptions={{}} />);
    const crop = mount(<ProcessingNodeOption name="crop" defaultValue="3" pluginContext={context} taskOptions={{}} />);
    await replies();
    boundary.update();
    crop.update();

    expect(crop.find('.plugin-control').length).toBe(0);
    expect(boundary.find('.plugin-control').text()).toBe("edit");
    boundary.find('.plugin-control').simulate('click');
    expect(boundary.instance().getValue()).toBe('{"type": "Polygon"}');
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
