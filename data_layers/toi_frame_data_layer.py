'''
The Caffe data layer for training label classifier.
This layer will parse pixel values and actionness labels to the network.
'''
import sys
sys.path.insert(0, '/home/rhou/caffe/python')
import caffe
#from dataset.ucf_sports import UcfSports
from dataset.ucf101 import ucf101
import numpy as np
from utils.cython_bbox import bbox_overlaps
from utils.bbox_transform import bbox_transform

class RegDataLayer(caffe.Layer):
  def setup(self, bottom, top):
    self._batch_size = 1
    self._depth = 8
    self._height = 300
    self._width = 400
    #self.dataset = UcfSports('test', [self._height, self._width],
    #                         '/home/rhou/ucf_sports')
    self.dataset = ucf101('train', [self._height, self._width], '/home/rhou/ucf101_deep')
    self.num_classes = self.dataset.num_classes - 1
    self.anchors = self.dataset.get_anchors()

  def reshape(self, bottom, top):
    # Clip data.
    top[0].reshape(self._batch_size, 3, self._depth, self._height, self._width)
    # Ground truth labels.
    top[1].reshape(self._batch_size * 32, self.num_classes * 4)
    # Ground truth tois.
    top[2].reshape(self._batch_size * 32, 5)
    # Mask
    top[3].reshape(self._batch_size * 32, self.num_classes * 4)
    # Second tois.
    top[4].reshape(self._batch_size * 32, 5)

  def forward(self, bottom, top):
    [clips, labels, tmp_bboxes, _] \
      = self.dataset.next_batch(self._batch_size, self._depth)
    batch_clip = clips.transpose((0, 4, 1, 2, 3))
    batch_tois = np.empty((0, 5))
    batch_targets = np.empty((0, self.num_classes * 4))
    batch_masks = np.empty((0, self.num_classes * 4))
    batch_toi2 = np.empty((0, 5))

    i = 0
    for box in tmp_bboxes:
      gt_bboxes = np.mean(box, axis=1) / 16

      overlaps = bbox_overlaps(
        np.ascontiguousarray(self.anchors, dtype=np.float),
        np.ascontiguousarray(gt_bboxes, dtype=np.float))
      max_overlaps = overlaps.max(axis=1)
      gt_argmax_overlaps = overlaps.argmax(axis=0)
      argmax_overlaps = overlaps.argmax(axis=1)

      curr_labels = np.ones(self.anchors.shape[0]) * (-1)
      curr_labels[max_overlaps < 0.3] = 0
      curr_labels[max_overlaps >= 0.7] = labels[i]

      curr_labels[gt_argmax_overlaps] = labels[i]

      fg_inds = np.where(curr_labels > 0)[0]
      num_fg = len(fg_inds)
      if len(fg_inds) > 16:
        fg_inds = np.random.choice(fg_inds, size=(16))
        num_fg = 16

      curr_idx = np.arange(self._depth).reshape(1, self._depth)
      curr_idx = np.repeat(curr_idx, num_fg, axis=0).reshape(-1, 1)
      curr_idx = curr_idx + i * self._depth
      curr_bboxes = np.repeat(self.anchors[fg_inds], 8, axis=0)
      curr_gt = np.empty((0, 4))
      for i in xrange(num_fg):
        curr_gt = np.vstack((curr_gt, box[argmax_overlaps[i]] / 16))
      curr_labels = np.repeat(curr_labels[fg_inds], 8)

      [curr_targets, masks] = _map(curr_labels, curr_bboxes,
                                   curr_gt, self.num_classes, num_fg * 8)

      batch_tois = np.vstack((batch_tois,
                              np.hstack((np.zeros((curr_bboxes.shape[0], 1)),
                                         curr_bboxes))))
      batch_targets = np.vstack((batch_targets, curr_targets))
      batch_masks = np.vstack((batch_masks, masks))
      batch_toi2 = np.vstack((batch_toi2,
                              np.hstack((curr_idx,
                                         curr_bboxes))))
      i += 1

    top[1].reshape(*batch_targets.shape)
    top[2].reshape(*batch_tois.shape)
    top[3].reshape(*batch_masks.shape)
    top[4].reshape(*batch_toi2.shape)

    top[0].data[...] = batch_clip.astype(np.float32, copy=False)
    top[1].data[...] = batch_targets.astype(np.float32, copy=False)
    top[2].data[...] = batch_tois.astype(np.float32, copy=False)
    top[3].data[...] = batch_masks.astype(np.float32, copy=False)
    top[4].data[...] = batch_toi2.astype(np.float32, copy=False)

  def backward(self, top, propagate_down, bottom):
    """This layer does not propagate gradients."""
    pass

def _map(label, target, gt_bbox, l, n):
  diff = bbox_transform(target, gt_bbox)
  r_diff = np.zeros((n, l * 4))
  mask = np.zeros((n, l * 4))
  for i in xrange(len(label)):
    curr_label = int(label[i] - 1)
    r_diff[i, curr_label * 4 : curr_label * 4 + 4] = diff[i]
    mask[i, curr_label * 4 : curr_label * 4 + 4] = 1
  return r_diff, mask