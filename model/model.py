import torch
import torch.nn as nn
from torch.autograd import Variable
from numpy import prod
import model.modules.capsules as caps

class CapsuleNetwork(nn.Module):
	def __init__(self, img_shape, channels, primary_dim, num_classes, out_dim, num_routing, kernel_size=9, out1_features=512, out2_features=1024, use_cuda=True):
		super(CapsuleNetwork, self).__init__()
		self.use_cuda = use_cuda
		self.img_shape = img_shape
		self.num_classes = num_classes

		self.conv1 = nn.Conv2d(img_shape[0], channels, kernel_size)
		self.relu = nn.ReLU(inplace=True)

		self.primary = caps.PrimaryCapsules(channels, channels, primary_dim, kernel_size)
		
		primary_caps = int(channels / primary_dim * ( img_shape[1] - 2*(kernel_size-1) ) * ( img_shape[2] - 2*(kernel_size-1) ) / 4)
		self.digits = caps.RoutingCapsules(primary_dim, primary_caps, num_classes, out_dim, num_routing)

		self.decoder = nn.Sequential(
			nn.Linear(out_dim * num_classes, out1_features),
			nn.ReLU(inplace=True),
			nn.Linear(out1_features, out2_features),
			nn.ReLU(inplace=True),
			nn.Linear(out2_features, int(prod(img_shape)) ),
			nn.Sigmoid()
		)

	def forward(self, x):
		out = self.conv1(x)
		out = self.relu(out)
		out = self.primary(out)
		out = self.digits(out)
		preds = torch.norm(out, dim=-1)

		# Reconstruct the *predicted* image
		_, max_length_idx = preds.max(dim=1)	
		y = Variable(torch.sparse.torch.eye(self.num_classes))
		if self.use_cuda:
			y = y.cuda()

		y = y.index_select(dim=0, index=max_length_idx).unsqueeze(2)

		reconstructions = self.decoder( (out*y).view(out.size(0), -1) )
		reconstructions = reconstructions.view(-1, *self.img_shape)

		return preds, reconstructions
