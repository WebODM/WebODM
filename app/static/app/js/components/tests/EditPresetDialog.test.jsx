import React from 'react';
import { shallow } from 'enzyme';
import EditPresetDialog from '../EditPresetDialog';
import ProcessingNodeOption from '../ProcessingNodeOption';

const presetMock = require('../../tests/utils/MockLoader').load("preset.json");

describe('<EditPresetDialog />', () => {
  it('renders without exploding', () => {
    const wrapper = shallow(<EditPresetDialog 
             preset={presetMock}
             availableOptions={[]}
             saveAction={() => {}}
             deleteAction={() => {}}
        />);
    expect(wrapper.exists()).toBe(true);
  })

  it('gives each option the task and the photo positions, for plugins', () => {
    const task = {id: "1"}, getPhotoPositions = () => [];
    const wrapper = shallow(<EditPresetDialog
             preset={{id: -1, name: "(Custom)", options: [], system: true}}
             availableOptions={[{name: "boundary", type: "string", value: "", domain: "json", help: "Boundary"}]}
             task={task}
             getPhotoPositions={getPhotoPositions}
             saveAction={() => {}}
             deleteAction={() => {}}
        />);
    const option = wrapper.find(ProcessingNodeOption);

    expect(option.length).toBe(1);
    expect(option.props().task).toBe(task);
    expect(option.props().getPhotoPositions).toBe(getPhotoPositions);
  })
});
