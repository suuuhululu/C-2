import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from scripts.held_tilt_accuracy import perturbed_pose,rotation_error,accuracy_result


@pytest.mark.parametrize('angles',[[10.,-179.99,9.],[103.,-176.,104.],[90.,179.999,90.]])
def test_base_axis_probe_remains_correct_near_zyz_pole(angles):
    source=[568.,181.,36.,*angles]
    target=perturbed_pose(source,.5,.5)
    result=rotation_error(source,target)
    np.testing.assert_allclose([result['base_x_deg'],result['base_y_deg'],result['base_z_deg']],[.5,.5,0.],atol=1e-10)
    assert target[:3]==source[:3]
    assert result['rotation_error_deg']==pytest.approx(2**.5*.5)


def test_return_accuracy_distinguishes_probe_from_encoder_residual():
    source=[568.,181.,36.,103.,-176.,104.]
    assert accuracy_result(source,perturbed_pose(source,.5,0.))['status']=='TCP_REFERENCE_RETURN_OUTSIDE_TOLERANCE'
    result=accuracy_result(source,perturbed_pose(source,.008,-.006))
    assert result['status']=='TCP_REFERENCE_RETURN_PASS'
    assert result['rotation_error_deg']==pytest.approx(.01)
    assert not result['independent_block_plane_verified'] and not result['loaded_alignment']


def test_large_or_nonfinite_probe_is_not_a_trial_motion():
    source=[568.,181.,36.,103.,-176.,104.]
    for angle in (1.1,float('nan'),float('inf')):
        with pytest.raises(ValueError):perturbed_pose(source,angle,0.)
