import paddle
import paddle.nn as nn
from nets.module import BackboneNet,PoseNet
from nets.loss import JointHeatmapLoss,HandTypeLoss,RelRootDepthLoss
from config import cfg



class Model(nn.Layer):

    def __init__(self,backbone_net,pose_net):
        super(Model, self).__init__()

        self.backbone_net=backbone_net
        self.pose_net=pose_net

        self.joint_heatmap_loss=JointHeatmapLoss()
        self.rel_root_depth_loss=RelRootDepthLoss()
        self.hand_type_loss=HandTypeLoss()

    def render_gaussian_heatmap(self, joint_coord):
        x = paddle.arange(cfg.output_hm_shape[2])
        y = paddle.arange(cfg.output_hm_shape[1])
        z = paddle.arange(cfg.output_hm_shape[0])
        zz, yy, xx = paddle.meshgrid(z, y, x)
        xx = paddle.unsqueeze(xx, axis=[0, 0]).astype(paddle.float32).cuda()
        yy = paddle.unsqueeze(yy, axis=[0, 0]).astype(paddle.float32).cuda()
        zz = paddle.unsqueeze(zz, axis=[0, 0]).astype(paddle.float32).cuda()

        x = paddle.unsqueeze(joint_coord[:, :, 0], axis=[-1, -1, -1])
        y = paddle.unsqueeze(joint_coord[:, :, 1], axis=[-1, -1, -1])
        z = paddle.unsqueeze(joint_coord[:, :, 2], axis=[-1, -1, -1])
        heatmap = paddle.exp(
            -(((xx - x) / cfg.sigma) ** 2) / 2 - (((yy - y) / cfg.sigma) ** 2) / 2 - (((zz - z) / cfg.sigma) ** 2) / 2)
        heatmap = heatmap * 255
        return heatmap

    def forward(self, inputs, targets, meta_info, mode):
        input_img = inputs['img']
        batch_size = input_img.shape[0]
        img_feat = self.backbone_net(input_img)
        print(img_feat.shape)
        joint_heatmap_out, rel_root_depth_out, hand_type = self.pose_net(img_feat)

        if mode == 'train':
            target_joint_heatmap = self.render_gaussian_heatmap(targets['joint_coord'])

            loss = {}
            loss['joint_heatmap'] = self.joint_heatmap_loss(joint_heatmap_out, target_joint_heatmap,
                                                            meta_info['joint_valid'])
            loss['rel_root_depth'] = self.rel_root_depth_loss(rel_root_depth_out, targets['rel_root_depth'],
                                                              meta_info['root_valid'])
            loss['hand_type'] = self.hand_type_loss(hand_type, targets['hand_type'], meta_info['hand_type_valid'])
            return loss
        elif mode == 'test':
            out = {}
            val_z, idx_z = paddle.max(joint_heatmap_out, 2)
            val_zy, idx_zy = paddle.max(val_z, 2)
            val_zyx, joint_x = paddle.max(val_zy, 2)
            joint_x = joint_x[:, :, None]
            joint_y = paddle.gather(idx_zy, 2, joint_x)
            joint_z = paddle.gather(idx_z, 2, joint_y[:, :, :, None].repeat(1, 1, 1, cfg.output_hm_shape[1]))[:, :, 0, :]
            joint_z = paddle.gather(joint_z, 2, joint_x)
            joint_coord_out = paddle.concat((joint_x, joint_y, joint_z), 2).float()
            out['joint_coord'] = joint_coord_out
            out['rel_root_depth'] = rel_root_depth_out
            out['hand_type'] = hand_type
            if 'inv_trans' in meta_info:
                out['inv_trans'] = meta_info['inv_trans']
            if 'joint_coord' in targets:
                out['target_joint'] = targets['joint_coord']
            if 'joint_valid' in meta_info:
                out['joint_valid'] = meta_info['joint_valid']
            if 'hand_type_valid' in meta_info:
                out['hand_type_valid'] = meta_info['hand_type_valid']
            return out

def init_weights(m):
    if type(m) == nn.Conv2DTranspose:
        m.weight = m.create_parameter(m.weight.shape,m._param_attr, m.weight.dtype, nn.initializer.Normal(std=0.001))
    elif type(m) == nn.Conv2D:
        m.weight = m.create_parameter(m.weight.shape, m._param_attr,m.weight.dtype, nn.initializer.Normal(std=0.001))
        m.bias = m.create_parameter(attr= m._bias_attr,shape=m.bias.shape, default_initializer=nn.initializer.Constant(value=0.0),is_bias=True)
    elif type(m) == nn.BatchNorm2D:
        m.weight = m.create_parameter(m.weight.shape,m._weight_attr, m.weight.dtype, nn.initializer.Constant(1.0))
        m.bias = m.create_parameter(shape=m.bias.shape, default_initializer=nn.initializer.Constant(value=0.0),is_bias=True)
    elif type(m) == nn.Linear:
        m.weight = m.create_parameter(shape=m.weight.shape,attr=m._weight_attr, dtype=m.weight.dtype,default_initializer= nn.initializer.Normal(std=0.01))
        m.bias = m.create_parameter(shape=m.bias.shape,attr=m._bias_attr, default_initializer=nn.initializer.Constant(value=0.0),is_bias=True)

def get_model(mode, joint_num):
    backbone_net = BackboneNet()
    pose_net = PoseNet(joint_num)

    if mode == 'train':
        backbone_net.init_weights()
        pose_net.apply(init_weights)

    model = Model(backbone_net, pose_net)
    return model



if __name__=="__main__":
    model=get_model('train',21)